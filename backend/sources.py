"""
Data connectors: file upload, database, REST API.

Each loader returns a plain DataFrame (capped at MAX_ROWS) plus a short
description of where it came from. Column mapping and feature building are
NOT done here; features.prepare() does that for every source the same way.
"""
import io
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlparse

import pandas as pd

MAX_ROWS = int(os.environ.get("MOMO_MAX_ROWS", 1_000_000))
MAX_UPLOAD_MB = int(os.environ.get("MOMO_MAX_UPLOAD_MB", 300))
ALLOW_PRIVATE_HOSTS = os.environ.get("MOMO_ALLOW_PRIVATE_HOSTS", "1") == "1"
SUPPORTED = [".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls", ".json", ".jsonl", ".ndjson", ".parquet",
             ".csv.gz", ".csv.zip", ".json.gz"]


class SourceError(ValueError):
    pass


def _cap(df: pd.DataFrame, notes: list):
    if len(df) > MAX_ROWS:
        notes.append(f"Dataset has {len(df):,} rows; a random sample of {MAX_ROWS:,} was analysed "
                     "(raise MOMO_MAX_ROWS to change this).")
        df = df.sample(MAX_ROWS, random_state=1).sort_index().reset_index(drop=True)
    return df


def _records_to_frame(obj, path: str | None = None) -> pd.DataFrame:
    if path:
        for key in path.split("."):
            if isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                raise SourceError(f"Records path '{path}' was not found in the JSON (stopped at '{key}').")
    if isinstance(obj, dict):  # find the first list of records inside the object
        lists = [v for v in obj.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            obj = lists[0]
        else:
            obj = [obj]
    if not isinstance(obj, list) or not obj:
        raise SourceError("The JSON did not contain a list of transaction records.")
    return pd.json_normalize(obj)


def load_file(fileobj, filename: str):
    """Parse an uploaded file. Returns (DataFrame, notes)."""
    name = (filename or "").lower()
    fileobj.seek(0, 2)
    size = fileobj.tell()
    fileobj.seek(0)
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        raise SourceError(f"File is {size / 1e6:.0f} MB; the limit is {MAX_UPLOAD_MB} MB.")
    if size == 0:
        raise SourceError("The file is empty.")
    notes = []
    comp = "gzip" if name.endswith(".gz") else "zip" if name.endswith(".zip") else None
    base = re.sub(r"\.(gz|zip)$", "", name)
    ext = os.path.splitext(base)[1]
    try:
        if ext in (".csv", ".txt", ".tsv", ""):
            if ext == ".csv":
                df = pd.read_csv(fileobj, compression=comp, nrows=MAX_ROWS * 2)
            elif ext == ".tsv":
                df = pd.read_csv(fileobj, sep="\t", compression=comp, nrows=MAX_ROWS * 2)
            else:  # .txt or unknown: let pandas sniff the delimiter
                df = pd.read_csv(fileobj, sep=None, engine="python", compression=comp, nrows=MAX_ROWS * 2)
        elif ext in (".xlsx", ".xlsm", ".xls"):
            df = pd.read_excel(fileobj)
        elif ext in (".jsonl", ".ndjson"):
            df = pd.read_json(fileobj, lines=True, compression=comp)
        elif ext == ".json":
            raw = fileobj.read()
            if comp == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            try:
                df = _records_to_frame(json.loads(raw))
            except json.JSONDecodeError:
                df = pd.read_json(io.BytesIO(raw), lines=True)
        elif ext == ".parquet":
            df = pd.read_parquet(fileobj)
        else:
            raise SourceError(f"'{ext}' files are not supported. Use: CSV, TSV, Excel, JSON, JSON Lines or Parquet "
                              "(optionally .gz / .zip compressed).")
    except SourceError:
        raise
    except ImportError as e:
        raise SourceError(f"A library needed for this file type is missing: {e}")
    except Exception as e:
        raise SourceError(f"Could not read '{filename}': {str(e)[:200]}")
    if df.empty:
        raise SourceError("The file was read but contains no rows.")
    return _cap(df, notes), notes


# ------------------------------------------------------------------ database
_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|attach|detach|pragma|"
                        r"exec|execute|call|merge|replace|vacuum|copy|into)\b", re.I)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)?$")
DRIVERS = {"sqlite": "sqlite", "postgresql": "postgresql+psycopg2", "mysql": "mysql+pymysql"}


def load_database(cfg: dict):
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    dialect = cfg.get("dialect", "sqlite")
    if dialect not in DRIVERS:
        raise SourceError(f"Unsupported database '{dialect}'. Use sqlite, postgresql or mysql.")
    table, query = (cfg.get("table") or "").strip(), (cfg.get("query") or "").strip().rstrip(";")
    if query:
        if _FORBIDDEN.search(query) or ";" in query or not re.match(r"^\s*(select|with)\b", query, re.I):
            raise SourceError("Only a single read-only SELECT query is allowed.")
        sql = query
    elif table:
        if not _IDENT.match(table):
            raise SourceError("Table name may only contain letters, digits, underscores and one schema dot.")
        sql = f"SELECT * FROM {table}"
    else:
        raise SourceError("Enter a table name or a SELECT query.")

    if dialect == "sqlite":
        path = (cfg.get("database") or "").strip()
        if not path or not os.path.exists(path):
            raise SourceError(f"SQLite file not found on the server: '{path}'.")
        url = f"sqlite:///file:{path}?mode=ro&uri=true"
    else:
        if not cfg.get("host") or not cfg.get("database"):
            raise SourceError("Host and database name are required.")
        _check_host(cfg["host"])
        url = URL.create(DRIVERS[dialect], username=cfg.get("username") or None, password=cfg.get("password") or None,
                         host=cfg["host"], port=int(cfg["port"]) if cfg.get("port") else None, database=cfg["database"])
    limit = int(cfg.get("max_rows") or MAX_ROWS)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 10} if dialect != "sqlite" else {})
        with engine.connect() as conn:
            if dialect in ("postgresql", "mysql"):
                conn.execute(text("SET TRANSACTION READ ONLY"))
            chunks, total = [], 0
            for chunk in pd.read_sql(text(sql), conn, chunksize=50_000):
                chunks.append(chunk); total += len(chunk)
                if total >= min(limit, MAX_ROWS):
                    break
        engine.dispose()
    except Exception as e:
        msg = str(e).split("\n")[0][:220]
        raise SourceError(f"Database error: {msg}")
    if not chunks:
        raise SourceError("The query returned no rows.")
    df = pd.concat(chunks, ignore_index=True).head(min(limit, MAX_ROWS))
    return df, [f"Read {len(df):,} rows from {dialect} (read-only connection)."]


# ------------------------------------------------------------------ REST API
def _check_host(host: str):
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        raise SourceError(f"Could not resolve host '{host}'.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise SourceError("That address is blocked (link-local / metadata ranges are never allowed).")
        if (ip.is_private or ip.is_loopback) and not ALLOW_PRIVATE_HOSTS:
            raise SourceError("Private and local addresses are disabled (set MOMO_ALLOW_PRIVATE_HOSTS=1 to allow).")


def load_api(cfg: dict):
    import httpx

    url = (cfg.get("url") or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise SourceError("Enter a full URL starting with http:// or https://.")
    _check_host(p.hostname)
    headers = {}
    for line in (cfg.get("headers") or "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
    method = (cfg.get("method") or "GET").upper()
    body = None
    if method == "POST" and (cfg.get("body") or "").strip():
        try:
            body = json.loads(cfg["body"])
        except json.JSONDecodeError:
            raise SourceError("The request body must be valid JSON.")
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as c:
            r = c.request(method, url, headers=headers, json=body)
    except httpx.HTTPError as e:
        raise SourceError(f"Could not reach the API: {str(e)[:160]}")
    if r.status_code >= 400:
        raise SourceError(f"The API answered {r.status_code}.")
    if len(r.content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise SourceError("The API response is larger than the upload limit.")
    ctype = r.headers.get("content-type", "")
    try:
        if "csv" in ctype or url.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(r.content))
        else:
            df = _records_to_frame(r.json(), (cfg.get("records_path") or "").strip() or None)
    except SourceError:
        raise
    except Exception as e:
        raise SourceError(f"Could not read the API response as transactions: {str(e)[:160]}")
    notes = [f"Fetched {len(df):,} records from {p.hostname}."]
    return _cap(df, notes), notes

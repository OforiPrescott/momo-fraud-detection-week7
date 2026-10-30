"""
MoMo Fraud & Intrusion Detection - API (Weeks 7-8).

This file only wires things together; each concern lives in its own module:
  schema.py     column vocabulary          features.py   raw data -> model features
  scoring.py    model + explanations       insights.py   automatic interpretation
  sources.py    file / database / API      sessions.py   analysed-dataset store
  stream.py     real-time engine + SSE     overview.py   project-level summary
  auth.py       accounts, sign-in, API keys

Every /api/ route except health and sign-in/registration requires a signed-in user (session cookie
or personal X-API-Key). Analyses and the live monitor are private to the user who created them.

Run (from the project root):
    uvicorn backend.main:app --reload --port 8000
The React dashboard (frontend/) talks to this API. After `npm run build` in
frontend/, this same server also serves the dashboard at http://localhost:8000
"""
import asyncio
import io
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import admin, auth, drift, features, insights, overview, scoring, sessions, sources, stream
from .security import SecurityHeaders, csv_safe
from .schema import KNOWN_TYPES

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
DIST = os.path.join(HERE, "..", "frontend", "dist")


@asynccontextmanager
async def lifespan(app):
    stream.LOOP = asyncio.get_running_loop()
    task = asyncio.create_task(_live_analysis_loop())
    yield
    task.cancel()


async def _live_analysis_loop():
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(3)
        stream.evict_idle()
        for ws in stream.workspaces():
            if ws.engine.dirty and ws.hub.queues:
                try:
                    res = await loop.run_in_executor(None, ws.engine.live_analysis, ws.currency)
                    if res:
                        ws.hub.publish("analysis", res)
                except Exception as e:  # never let a bad window kill the loop
                    print("live analysis skipped:", e)


def _forget_user(uid: int):
    sessions.drop_owner(uid)
    stream.drop(uid)


auth.ON_DELETE.append(_forget_user)

logging.basicConfig(level=os.environ.get("MOMO_LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
_DOCS = os.environ.get("MOMO_API_DOCS", "1") == "1"  # set 0 to hide /docs on a public server
app = FastAPI(title="MoMo Fraud & Intrusion Detection API", lifespan=lifespan, dependencies=[Depends(auth.guard)],
              docs_url="/docs" if _DOCS else None, redoc_url=None, openapi_url="/openapi.json" if _DOCS else None)
app.include_router(auth.router)
app.include_router(admin.router)
User = Depends(auth.current_user)
# Same-origin by default: the dashboard is served by this server, so no other website needs to call the API.
# List extra sites in MOMO_CORS_ORIGINS only if you host a separate frontend (cookies are never sent cross-site).
_CORS = [o.strip() for o in os.environ.get("MOMO_CORS_ORIGINS", "").split(",") if o.strip()]
if _CORS:
    app.add_middleware(CORSMiddleware, allow_origins=_CORS, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-API-Key"])
app.add_middleware(SecurityHeaders)


def _clean(o):
    """Make numpy / NaN values JSON-safe."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (o != o or o in (float("inf"), float("-inf"))) else float(o)
    return o


def _json(o):
    return Response(content=json.dumps(_clean(o)), media_type="application/json")


# ------------------------------------------------------------------ legacy (Week 3-7) endpoints
@app.get("/api/health")
def health():
    try:
        scoring.bundle(); model = True
    except scoring.ModelMissing:
        model = False
    return {"status": "ok", "model_loaded": model}


@app.get("/api/summary")
def get_summary():
    path = os.path.join(DATA_DIR, "dashboard_summary.json")
    if not os.path.exists(path):
        raise HTTPException(404, "Summary not found. Run backend/precompute_dashboard_data.py first.")
    with open(path) as f:
        return json.load(f)


@app.get("/api/flagged")
def get_flagged(pattern: str = "sim_swap_takeover", limit: int = 50):
    valid = {"sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag"}
    if pattern not in valid:
        raise HTTPException(400, f"pattern must be one of {valid}")
    path = os.path.join(DATA_DIR, "flagged_samples.csv")
    if not os.path.exists(path):
        raise HTTPException(404, "Samples not found. Run backend/precompute_dashboard_data.py first.")
    df = pd.read_csv(path)
    return df[df["matched_pattern"] == pattern].head(limit).to_dict(orient="records")


class ScoreRequest(BaseModel):
    amount: float
    amount_log: Optional[float] = None
    oldbalanceOrg: float = 0
    newbalanceOrig: float = 0
    oldbalanceDest: float = 0
    newbalanceDest: float = 0
    balance_error_orig: Optional[float] = None
    balance_error_dest: Optional[float] = None
    hour_of_day: int = 12
    is_night: Optional[int] = None
    orig_txn_count_so_far: int = 0
    orig_avg_amount_so_far: Optional[float] = None
    amount_to_avg_ratio: Optional[float] = None
    orig_distinct_devices: int = 1
    orig_ever_sim_change: int = 0
    dest_distinct_senders: int = 0
    type: str


@app.post("/api/score")
def score_transaction(req: ScoreRequest):
    """Score ONE transaction. Missing derived fields are filled in, and the answer now includes WHY."""
    d = req.model_dump()
    amt = d["amount"]
    d["amount_log"] = d["amount_log"] if d["amount_log"] is not None else float(np.log1p(max(amt, 0)))
    d["balance_error_orig"] = d["balance_error_orig"] if d["balance_error_orig"] is not None else \
        d["oldbalanceOrg"] - amt - d["newbalanceOrig"]
    d["balance_error_dest"] = d["balance_error_dest"] if d["balance_error_dest"] is not None else \
        d["oldbalanceDest"] + amt - d["newbalanceDest"]
    d["is_night"] = d["is_night"] if d["is_night"] is not None else int(d["hour_of_day"] in (0, 1, 2, 3, 4))
    d["orig_avg_amount_so_far"] = d["orig_avg_amount_so_far"] if d["orig_avg_amount_so_far"] is not None else amt
    d["amount_to_avg_ratio"] = d["amount_to_avg_ratio"] if d["amount_to_avg_ratio"] is not None else \
        amt / (d["orig_avg_amount_so_far"] + 1.0)
    typ = d.pop("type").upper()
    if typ not in KNOWN_TYPES:
        raise HTTPException(400, f"type must be one of {KNOWN_TYPES}")
    for t in KNOWN_TYPES:
        d[f"type_{t}"] = int(typ == t)
    try:
        X = pd.DataFrame([d])[scoring.feature_columns()].astype("float32")
        p = float(scoring.score(X)[0])
    except scoring.ModelMissing as e:
        raise HTTPException(404, str(e))
    return {"risk_score": round(p, 4), "predicted_label": int(p >= 0.5),
            "reasons": scoring.explain_rows(X, top=6)[0], "model_features_used": scoring.feature_columns()}


@app.get("/api/model-flagged")
def model_flagged(limit: int = 25):
    df = pd.read_csv(os.path.join(DATA_DIR, "scoring_sample.csv"))
    X, frame, meta = features.prepare(df)
    df["risk_score"] = scoring.score(X)
    top = df.sort_values("risk_score", ascending=False).head(limit)
    cols = ["step", "type", "amount", "nameOrig", "nameDest", "risk_score", "any_attack_flag"]
    return top[cols].to_dict(orient="records")


# ------------------------------------------------------------------ overview + capabilities
auth.PUBLIC_PATHS.add("/api/public/highlights")


@app.get("/api/public/highlights")
def public_highlights():
    """Headline figures for the sign-in page (no account needed): read from the project's result files, so the
    landing page always matches the model actually shipped."""
    return overview.highlights()


@app.get("/api/overview")
def get_overview():
    try:
        return _json(overview.build())
    except scoring.ModelMissing as e:
        raise HTTPException(404, str(e))


@app.get("/api/capabilities")
def capabilities():
    return {"formats": sources.SUPPORTED, "max_upload_mb": sources.MAX_UPLOAD_MB, "max_rows": sources.MAX_ROWS,
            "databases": ["sqlite", "postgresql", "mysql"] if sources.ALLOW_SERVER_FILES else ["postgresql", "mysql"],
            "model_features": scoring.feature_columns() if os.path.exists(scoring.MODEL_PATH) else []}


# ------------------------------------------------------------------ batch analysis
def _analyse(user: dict, df_raw: pd.DataFrame, source: dict, notes: list, threshold: float, cur: str, events=None):
    t0 = time.time()
    try:
        X, frame, meta = features.prepare(df_raw, events)
        risk = scoring.score(X)
    except (ValueError, sources.SourceError) as e:
        raise HTTPException(422, str(e))
    except scoring.ModelMissing as e:
        raise HTTPException(404, str(e))
    frame = frame.copy()
    frame["risk"] = risk.astype("float32")
    meta["drift"] = drift.compute(X, meta["feature_sources"])
    meta["notes"] = notes + meta["notes"]
    y = frame["label"].to_numpy() if meta["label_name"] else None
    curves = insights.build_curves(risk, frame["amount"].to_numpy(dtype=float), y)
    s = sessions.put(user["id"], frame, meta, curves, source)
    return _respond(s, threshold, cur, took=time.time() - t0)


def _respond(s: sessions.Session, threshold: float, cur: str, took: float | None = None):
    res = insights.analyze(s.frame, s.meta, s.curves, threshold, cur=cur, window_label=s.source.get("name"))
    res["analysis_id"] = s.id
    res["source"] = s.source
    d = s.meta.get("drift") or {"available": False, "features": []}
    drift_finding = drift.insight(d)
    if drift_finding:  # place it after critical/high findings, before the informational ones
        order = {"critical": 0, "high": 1, "medium": 2, "info": 3, "good": 4}
        res["insights"] = sorted(res["insights"] + [drift_finding], key=lambda i: order.get(i["severity"], 3))
    res["data_quality"] = {
        "coverage_pct": s.meta["coverage_pct"], "warnings": s.meta["warnings"], "notes": s.meta["notes"],
        "features": [{"feature": f, "label": scoring.LABELS.get(f, f), "source": src,
                      "importance": round(s.meta["importance"][f], 4)}
                     for f, src in sorted(s.meta["feature_sources"].items(), key=lambda kv: -s.meta["importance"][kv[0]])],
        "label_name": s.meta["label_name"], "rule_columns": s.meta["rule_columns"],
        "drift": d,
    }
    if took is not None:
        res["took_seconds"] = round(took, 2)
    return _json(res)


def _thr(t: float):
    return float(min(max(t, 0.0), 1.0))


@app.post("/api/analyze/upload")
def analyze_upload(file: UploadFile = File(...), events: Optional[UploadFile] = File(None),
                   threshold: float = Form(0.5), currency: str = Form(""), user: dict = User):
    try:
        df, notes = sources.load_file(file.file, file.filename)
        ev = None
        if events is not None and events.filename:
            ev, n2 = sources.load_file(events.file, events.filename); notes += n2
    except sources.SourceError as e:
        raise HTTPException(422, str(e))
    return _analyse(user, df, {"kind": "file", "name": file.filename, "detail": f"{len(df):,} rows"}, notes, _thr(threshold),
                    currency, ev)


class DbRequest(BaseModel):
    dialect: str = Field("sqlite", max_length=20)
    host: str = Field("", max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    database: str = Field("", max_length=1024)
    username: str = Field("", max_length=255)
    password: str = Field("", max_length=1024)
    table: str = Field("", max_length=255)
    query: str = Field("", max_length=20_000)
    max_rows: Optional[int] = Field(None, ge=1)
    threshold: float = 0.5
    currency: str = Field("", max_length=10)


@app.post("/api/analyze/database")
def analyze_database(req: DbRequest, user: dict = User):
    try:
        df, notes = sources.load_database(req.model_dump())
    except sources.SourceError as e:
        raise HTTPException(422, str(e))
    label = req.table or "custom query"
    return _analyse(user, df, {"kind": "database", "name": f"{req.dialect}: {label}", "detail": f"{len(df):,} rows"}, notes,
                    _thr(req.threshold), req.currency)


class ApiRequest(BaseModel):
    url: str = Field(max_length=2048)
    method: str = Field("GET", pattern="^(GET|POST|get|post)$")
    headers: str = Field("", max_length=8_000)
    body: str = Field("", max_length=200_000)
    records_path: str = Field("", max_length=255)
    threshold: float = 0.5
    currency: str = Field("", max_length=10)


@app.post("/api/analyze/api")
def analyze_api(req: ApiRequest, user: dict = User):
    try:
        df, notes = sources.load_api(req.model_dump())
    except sources.SourceError as e:
        raise HTTPException(422, str(e))
    host = req.url.split("//")[-1].split("/")[0]
    return _analyse(user, df, {"kind": "api", "name": host, "detail": f"{len(df):,} records"}, notes, _thr(req.threshold),
                    req.currency)


class SampleRequest(BaseModel):
    threshold: float = 0.5
    currency: str = ""


@app.post("/api/analyze/sample")
def analyze_sample(req: SampleRequest, user: dict = User):
    path = os.path.join(DATA_DIR, "scoring_sample.csv")
    if not os.path.exists(path):
        raise HTTPException(404, "scoring_sample.csv not found. Run backend/precompute_dashboard_data.py first.")
    df = pd.read_csv(path)
    return _analyse(user, df, {"kind": "sample", "name": "Project sample (5,000 transactions)", "detail": "built-in, labelled"},
                    [], _thr(req.threshold), req.currency)


def _session(sid: str, user: dict) -> sessions.Session:
    s = sessions.get(sid, user["id"])
    if not s:
        raise HTTPException(404, "This analysis has expired from memory. Run the analysis again.")
    return s


@app.get("/api/analysis/{sid}")
def get_analysis(sid: str, threshold: float = 0.5, currency: str = "", user: dict = User):
    return _respond(_session(sid, user), _thr(threshold), currency)


def _filtered(s, threshold, type_, q, min_risk, only_flagged=True):
    f = s.frame
    mask = (f["risk"] >= max(threshold, min_risk)) if only_flagged else (f["risk"] >= min_risk)
    if type_:
        mask &= f["type"] == type_
    if q:
        ql = q.lower()
        m2 = pd.Series(False, index=f.index)
        for c in ("nameOrig", "nameDest"):
            if c in f:
                m2 |= f[c].astype(str).str.lower().str.contains(ql, regex=False)
        mask &= m2
    return f[mask]


@app.get("/api/analysis/{sid}/flagged")
def flagged_rows(sid: str, threshold: float = 0.5, type: str = "", q: str = "", min_risk: float = 0.0,
                 sort: str = "risk", desc: bool = True, page: int = 0, page_size: int = Query(25, le=200),
                 user: dict = User):
    s = _session(sid, user)
    sub = _filtered(s, threshold, type, q, min_risk)
    sort = sort if sort in sub.columns else "risk"
    sub = sub.sort_values(sort, ascending=not desc)
    total = len(sub)
    sub = sub.iloc[page * page_size:(page + 1) * page_size]
    cols = [c for c in ["row_id", "step", "type", "amount", "nameOrig", "nameDest", "risk", "label",
                        "sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag"] if c in sub]
    return _json({"total": total, "page": page, "rows": sub[cols].to_dict(orient="records")})


@app.get("/api/analysis/{sid}/case/{row_id}")
def case_detail(sid: str, row_id: int, threshold: float = 0.5, user: dict = User):
    s = _session(sid, user)
    f = s.frame
    hit = f[f["row_id"] == row_id]
    if hit.empty:
        raise HTTPException(404, "Transaction not found.")
    row = hit.iloc[0]
    cols = scoring.feature_columns()
    why = scoring.explain_rows(hit[cols].astype("float32"), top=6)[0]
    related = []
    for key, other in (("nameOrig", "sender"), ("nameDest", "receiver")):
        if key in f and pd.notna(row.get(key)):
            sub = f[(f[key] == row[key]) & (f["row_id"] != row_id) & (f["risk"] >= threshold)]
            if len(sub):
                related.append({"relation": f"Other flagged transactions with the same {other}", "count": int(len(sub)),
                                "value": float(sub["amount"].sum()),
                                "examples": sub.sort_values("risk", ascending=False).head(4)[
                                    ["row_id", "type", "amount", "risk"]].to_dict(orient="records")})
    detail = {c: row[c] for c in ("row_id", "step", "type", "amount", "nameOrig", "nameDest", "oldbalanceOrg",
                                  "newbalanceOrig", "label", "sim_swap_takeover", "pin_sharing_flag",
                                  "agent_collusion_flag") if c in row.index and pd.notna(row[c])}
    risk = float(row["risk"])
    action = ("Hold and call the customer" if risk >= max(threshold, 0.9) else
              "Ask for step-up verification" if risk >= threshold else "Allow, keep watching" if risk >= 0.3 else "Allow")
    return _json({"transaction": detail, "risk": risk, "action": action, "why": why,
                  "features": {c: float(row[c]) for c in cols}, "related": related,
                  "source": {c: s.meta["feature_sources"][c] for c in cols}})


@app.get("/api/analysis/{sid}/export.csv")
def export_csv(sid: str, threshold: float = 0.5, type: str = "", q: str = "", user: dict = User):
    s = _session(sid, user)
    sub = _filtered(s, threshold, type, q, 0.0).sort_values("risk", ascending=False)
    cols = [c for c in ["row_id", "step", "type", "amount", "nameOrig", "nameDest", "risk", "label"] if c in sub]
    out = sub[cols].copy()
    for c in out.columns:  # text cells starting with = + - @ would run as formulas in Excel
        if out[c].dtype == object or pd.api.types.is_string_dtype(out[c]):
            out[c] = out[c].map(csv_safe)
    buf = io.StringIO(); out.to_csv(buf, index=False)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="flagged_{sid}.csv"'})


# ------------------------------------------------------------------ real-time
@app.post("/api/ingest")
async def ingest(request: Request, user: dict = User):
    """A MoMo platform / webhook pushes one transaction (object) or many (list), authenticated with the user's
    personal X-API-Key. Each is scored immediately and pushed to that user's open dashboards. Fields may use any
    of the accepted column names."""
    ws = stream.workspace(user["id"])
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body must be JSON: a transaction object or a list of them.")
    txns = body if isinstance(body, list) else body.get("transactions", [body]) if isinstance(body, dict) else None
    if not txns or not all(isinstance(t, dict) for t in txns) or len(txns) > 5000:
        raise HTTPException(400, "Send one transaction object or a list (max 5,000).")
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, ws.engine.process, txns, "ingest")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except scoring.ModelMissing as e:
        raise HTTPException(404, str(e))
    for ev in res:
        ws.hub.publish("txn", ev)
    return {"scored": len(res), "flagged": sum(e["flagged"] for e in res),
            "results": [{"id": e["id"], "risk": e["risk"], "flagged": e["flagged"], "why": e.get("why", [])} for e in res]}


@app.get("/api/stream")
async def sse(request: Request, user: dict = User):
    ws = stream.workspace(user["id"])
    q = ws.hub.subscribe()

    async def gen():
        try:
            snap = ws.engine.snapshot(); snap["replay"] = ws.replay.status()
            yield f"event: snapshot\ndata: {json.dumps(snap, default=str)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev, data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {ev}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            ws.hub.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ReplayRequest(BaseModel):
    action: str = "start"            # start | stop | rate
    source: str = "sample"           # sample | <analysis id>
    rate: float = 5


@app.post("/api/stream/replay")
async def replay_ctl(req: ReplayRequest, user: dict = User):
    ws = stream.workspace(user["id"])
    rate = float(min(max(req.rate, 0.5), 200))
    if req.action == "stop":
        await ws.replay.stop()
    elif req.action == "rate":
        ws.replay.set_rate(rate)
    else:
        if req.source == "sample":
            df = pd.read_csv(os.path.join(DATA_DIR, "scoring_sample.csv"))
            name = "Project sample"
        else:
            s = _session(req.source, user)
            df = s.frame.drop(columns=["risk", "row_id"], errors="ignore")
            name = s.source.get("name", "analysis")
        df = df.sample(frac=1, random_state=int(time.time()) % 10000).reset_index(drop=True)
        rows = [{k: v for k, v in r.items() if v == v} for r in df.to_dict("records")]
        ws.engine.reset()
        await ws.replay.start(rows, rate, name)
    return ws.replay.status()


class ConfigRequest(BaseModel):
    threshold: Optional[float] = None
    currency: Optional[str] = None


@app.post("/api/stream/config")
def stream_config(req: ConfigRequest, user: dict = User):
    ws = stream.workspace(user["id"])
    if req.threshold is not None:
        ws.engine.threshold = _thr(req.threshold)
        ws.engine.dirty = True
    if req.currency is not None:
        ws.currency = req.currency
    return {"threshold": ws.engine.threshold}


@app.post("/api/stream/reset")
async def stream_reset(user: dict = User):
    ws = stream.workspace(user["id"])
    await ws.replay.stop()
    ws.engine.reset()
    return {"ok": True}


@app.get("/api/stream/analysis")
def stream_analysis(currency: str = "", user: dict = User):
    return _json(stream.workspace(user["id"]).engine.live_analysis(currency) or {"empty": True})


# ------------------------------------------------------------------ serve the built dashboard
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = os.path.join(DIST, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(DIST, "index.html"))

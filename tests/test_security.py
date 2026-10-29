"""Security tests: how credentials are stored, sign-in defences, CSRF, headers, isolation, file-handling limits."""
import gzip
import io
import os
import sqlite3

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import auth, scoring, sources
from backend.main import app
from backend.security import csv_safe

from conftest import PASSWORD, new_user


def _row(email):
    with sqlite3.connect(auth.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        return c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()


# ---------------------------------------------------------------- credential storage
def test_password_is_stored_only_as_salted_pbkdf2_hash(signed_in):
    stored = _row(signed_in.email)["password_hash"]
    assert PASSWORD not in stored
    algo, iterations, salt, digest = stored.split("$")
    assert algo == "pbkdf2_sha256" and int(iterations) >= 600_000 and salt and digest


def test_same_password_gives_different_hashes():
    assert auth.hash_password(PASSWORD) != auth.hash_password(PASSWORD)  # unique salt per user


def test_session_token_is_stored_only_as_hash(signed_in):
    token = signed_in.cookies.get(auth.COOKIE)
    with sqlite3.connect(auth.DB_PATH) as c:
        hashes = [r[0] for r in c.execute("SELECT token_hash FROM auth_sessions")]
    assert token not in hashes and auth._sha(token) in hashes


def test_session_cookie_is_httponly_and_samesite(client):
    email = f"cookie-{os.urandom(4).hex()}@example.org"
    r = client.post("/api/auth/register", json={"name": "Esi Owusu", "email": email, "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_api_key_is_stored_only_as_hash(signed_in):
    key = signed_in.post("/api/auth/api-key").json()["api_key"]
    row = _row(signed_in.email)
    assert row["api_key_hash"] == auth._sha(key) and key not in dict(row).values()


def test_old_weaker_hash_is_upgraded_at_sign_in(client):
    email = new_user(client)
    weak = auth.hash_password(PASSWORD).replace("$600000$", "$1000$")
    import base64, hashlib
    _, _, salt, _ = weak.split("$")
    weak = f"pbkdf2_sha256$1000${salt}${base64.b64encode(hashlib.pbkdf2_hmac('sha256', PASSWORD.encode(), base64.b64decode(salt), 1000)).decode()}"
    with sqlite3.connect(auth.DB_PATH) as c:
        c.execute("UPDATE users SET password_hash=? WHERE email=?", (weak, email))
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    assert _row(email)["password_hash"].split("$")[1] == "600000"


# ---------------------------------------------------------------- password policy + sign-in defences
@pytest.mark.parametrize("pw,why", [("short1", "8 characters"), ("password123", "too common"),
                                    ("aaaaaaa1", "repeats"), ("nolettersatall", "8 characters")])
def test_weak_passwords_are_rejected(client, pw, why):
    r = client.post("/api/auth/register", json={"name": "Ama Mensah", "email": "weak@example.org", "password": pw})
    assert r.status_code == 422 and why in r.json()["detail"]


def test_password_containing_email_or_name_is_rejected(client):
    r = client.post("/api/auth/register", json={"name": "Yaw Darko", "email": "kofiman@example.org",
                                                 "password": "kofiman2026"})
    assert r.status_code == 422
    r = client.post("/api/auth/register", json={"name": "Yaw Darko", "email": "x1@example.org",
                                                 "password": "Darko-2026x"})
    assert r.status_code == 422


def test_wrong_password_message_does_not_reveal_whether_email_exists(client):
    email = new_user(client)
    a = client.post("/api/auth/login", json={"email": email, "password": "Wrong-pass-1"}).json()["detail"]
    b = client.post("/api/auth/login", json={"email": "nobody-here@example.org", "password": "Wrong-pass-1"}).json()["detail"]
    assert a == b


def test_repeated_failed_sign_ins_are_throttled(client):
    email = new_user(client)
    codes = [client.post("/api/auth/login", json={"email": email, "password": f"Wrong-{i}x"}).status_code
             for i in range(auth.FAIL_LIMIT + 1)]
    assert codes[-1] == 429
    # even the right password is refused while throttled
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 429


def test_logout_ends_the_session(signed_in):
    assert signed_in.get("/api/auth/me").status_code == 200
    signed_in.post("/api/auth/logout")
    assert signed_in.get("/api/auth/me").status_code == 401


def test_security_activity_is_recorded(signed_in):
    signed_in.post("/api/auth/api-key")
    events = [e["event"] for e in signed_in.get("/api/auth/activity").json()]
    assert "register" in events and "api_key_created" in events


# ---------------------------------------------------------------- CSRF, CORS, headers
def test_cross_site_write_is_blocked(signed_in):
    r = signed_in.post("/api/auth/api-key", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_site_write_is_allowed(signed_in):
    assert signed_in.post("/api/auth/api-key", headers={"Origin": "http://testserver"}).status_code == 200


def test_security_headers_present(client):
    h = client.get("/api/health").headers
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["cache-control"] == "no-store"


def test_no_cors_by_default(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_api_requires_sign_in(client):
    for path in ("/api/overview", "/api/stream/analysis", "/api/auth/activity"):
        assert client.get(path).status_code == 401


def test_api_key_cannot_manage_keys(signed_in):
    key = signed_in.post("/api/auth/api-key").json()["api_key"]
    with TestClient(app) as robot:
        assert robot.get("/api/overview", headers={"X-API-Key": key}).status_code == 200
        assert robot.post("/api/auth/api-key", headers={"X-API-Key": key}).status_code == 403


# ---------------------------------------------------------------- isolation between users
def test_users_cannot_see_each_others_analyses(signed_in):
    sid = signed_in.post("/api/analyze/sample", json={"threshold": 0.5}).json()["analysis_id"]
    with TestClient(app) as other:
        new_user(other)
        assert other.get(f"/api/analysis/{sid}").status_code == 404
        assert other.get(f"/api/analysis/{sid}/export.csv").status_code == 404


# ---------------------------------------------------------------- files, exports, model
def test_csv_export_neutralises_formulas(signed_in):
    df = pd.DataFrame({"type": ["CASH_OUT"] * 3, "amount": [900000, 850000, 990000],
                       "nameOrig": ["=HYPERLINK(\"http://evil\")", "+1+1", "C1"], "nameDest": ["@SUM(A1)", "D2", "D3"],
                       "oldbalanceOrg": [900000, 850000, 990000], "newbalanceOrig": [0, 0, 0]})
    sid = signed_in.post("/api/analyze/upload", files={"file": ("x.csv", df.to_csv(index=False).encode())},
                         data={"threshold": "0"}).json()["analysis_id"]
    text = signed_in.get(f"/api/analysis/{sid}/export.csv", params={"threshold": 0}).text
    assert "'=HYPERLINK" in text and "'@SUM" in text and "'+1+1" in text
    assert csv_safe("C123") == "C123" and csv_safe(-5) == -5


def test_decompression_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(sources, "MAX_EXPANDED", 50_000)
    bomb = gzip.compress(b"type,amount\n" + b"PAYMENT,1\n" * 100_000)  # ~1 MB unpacked from a few KB
    with pytest.raises(sources.SourceError, match="expands"):
        sources.load_file(io.BytesIO(bomb), "bomb.csv.gz")


def test_tampered_model_is_refused(tmp_path):
    fake = tmp_path / "model.joblib"
    fake.write_bytes(b"not the real model")
    (tmp_path / "model.joblib.sha256").write_text(scoring.file_sha256(scoring.MODEL_PATH))
    with pytest.raises(scoring.ModelMissing, match="integrity"):
        scoring.verify_model_file(str(fake))


def test_shipped_model_passes_its_checksum():
    scoring.verify_model_file(scoring.MODEL_PATH)


def test_account_database_cannot_be_read_through_sqlite_connector(signed_in):
    r = signed_in.post("/api/analyze/database", json={"dialect": "sqlite", "database": auth.DB_PATH, "table": "users"})
    assert r.status_code == 422

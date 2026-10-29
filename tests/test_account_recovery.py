"""Forgotten-password reset and two-step sign-in (authenticator app + recovery codes)."""
import time

import pytest
from fastapi.testclient import TestClient

from backend import auth, mailer, mfa
from backend.main import app

from conftest import PASSWORD, new_user

NEW_PASSWORD = "Fresh-start-2026"


@pytest.fixture
def outbox(monkeypatch):
    """Captures reset emails instead of sending them."""
    sent = []
    monkeypatch.setattr(mailer, "send_password_reset", lambda to, name, link, minutes: sent.append((to, link)))
    return sent


def _token(link):
    return link.split("#reset=")[1]


# ---------------------------------------------------------------- TOTP primitives
def test_totp_matches_rfc6238_reference_vector():
    # RFC 6238 appendix B, SHA-1, T = 59 s -> 94287082 (8 digits); its last 6 digits are what 6-digit apps show
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890"
    assert mfa.code_at(secret, 59 // 30) == "287082"


def test_totp_rejects_replay_and_old_codes():
    s = mfa.new_secret()
    now = time.time()
    code = mfa.code_at(s, mfa.current_step(now))
    step = mfa.verify(s, code, None, now)
    assert step is not None
    assert mfa.verify(s, code, step, now) is None                                   # same code twice
    assert mfa.verify(s, mfa.code_at(s, mfa.current_step(now) - 5), None, now) is None  # 2.5 minutes old


# ---------------------------------------------------------------- forgotten password
def test_forgot_answers_the_same_for_unknown_email(client, outbox):
    email = new_user(client)
    a = client.post("/api/auth/forgot", json={"email": email}).json()
    b = client.post("/api/auth/forgot", json={"email": "nobody-at-all@example.org"}).json()
    assert a == b and len(outbox) == 1 and outbox[0][0] == email


def test_reset_link_changes_password_once_and_signs_out_everywhere(client, outbox):
    email = new_user(client)
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/forgot", json={"email": email})
    token = _token(outbox[-1][1])
    with TestClient(app) as other:
        assert other.post("/api/auth/reset", json={"token": token, "new_password": "password123"}).status_code == 422
        assert other.post("/api/auth/reset", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 200
        assert other.post("/api/auth/reset", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 400
        assert other.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
        assert other.post("/api/auth/login", json={"email": email, "password": NEW_PASSWORD}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401  # the old session was ended


def test_reset_token_is_stored_only_as_hash_and_expires(client, outbox):
    import sqlite3
    email = new_user(client)
    client.post("/api/auth/forgot", json={"email": email})
    token = _token(outbox[-1][1])
    with sqlite3.connect(auth.DB_PATH) as c:
        rows = [r[0] for r in c.execute("SELECT token_hash FROM reset_tokens")]
        assert token not in rows and auth._sha(token) in rows
        c.execute("UPDATE reset_tokens SET expires_at = 0")
    assert client.post("/api/auth/reset", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 400


def test_reset_requests_are_rate_limited(client, outbox):
    email = new_user(client)
    codes = [client.post("/api/auth/forgot", json={"email": email}).status_code for _ in range(6)]
    assert codes[-1] == 429 and len(outbox) == 5


def test_reset_link_uses_public_url_not_host_header(client, outbox, monkeypatch):
    monkeypatch.setattr(mailer, "PUBLIC_URL", "https://momo.example.org")
    email = new_user(client)
    client.post("/api/auth/forgot", json={"email": email}, headers={"Host": "evil.example"})
    assert outbox[-1][1].startswith("https://momo.example.org/#reset=")


# ---------------------------------------------------------------- two-step sign-in
def _enable_2fa(c):
    setup = c.post("/api/auth/2fa/setup", json={"password": PASSWORD}).json()
    secret = setup["secret"]
    assert setup["uri"].startswith("otpauth://totp/")
    r = c.post("/api/auth/2fa/enable", json={"code": mfa.code_at(secret, mfa.current_step())}).json()
    return secret, r["recovery_codes"]


def _fresh_code(secret):
    # the code just used at enable time cannot be replayed, so use the next time step
    return mfa.code_at(secret, mfa.current_step() + 1)


def test_two_step_sign_in_flow(client):
    email = new_user(client)
    secret, codes = _enable_2fa(client)
    assert len(codes) == 8 and client.get("/api/auth/me").json()["mfa_enabled"] is True
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()
    assert r["mfa_required"] and "id" not in r                     # password alone gives no session
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login/2fa", json={"mfa_token": r["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login/2fa", json={"mfa_token": r["mfa_token"], "code": _fresh_code(secret)})
    assert ok.status_code == 200 and client.get("/api/auth/me").status_code == 200


def test_challenge_is_single_use_and_limited(client):
    email = new_user(client)
    secret, _ = _enable_2fa(client)
    client.post("/api/auth/logout")
    tok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["mfa_token"]
    codes = [client.post("/api/auth/login/2fa", json={"mfa_token": tok, "code": "111111"}).status_code
             for _ in range(auth.MFA_MAX_ATTEMPTS + 1)]
    assert codes[-1] == 429
    # the challenge is gone: even the right code is refused now
    assert client.post("/api/auth/login/2fa", json={"mfa_token": tok, "code": _fresh_code(secret)}).status_code == 401


def test_recovery_code_works_once(client):
    email = new_user(client)
    _, codes = _enable_2fa(client)
    client.post("/api/auth/logout")
    for expected in (200, 401):
        client.post("/api/auth/logout")
        tok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["mfa_token"]
        assert client.post("/api/auth/login/2fa", json={"mfa_token": tok, "code": codes[0].upper()}).status_code == expected
    tok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["mfa_token"]
    assert client.post("/api/auth/login/2fa", json={"mfa_token": tok, "code": codes[1]}).status_code == 200
    assert client.get("/api/auth/2fa").json()["recovery_codes_left"] == 6


def test_password_reset_does_not_bypass_two_step(client, outbox):
    email = new_user(client)
    _enable_2fa(client)
    client.post("/api/auth/forgot", json={"email": email})
    client.post("/api/auth/reset", json={"token": _token(outbox[-1][1]), "new_password": NEW_PASSWORD})
    r = client.post("/api/auth/login", json={"email": email, "password": NEW_PASSWORD}).json()
    assert r.get("mfa_required") is True


def test_disable_needs_password_and_code(client):
    email = new_user(client)
    secret, _ = _enable_2fa(client)
    assert client.post("/api/auth/2fa/disable", json={"password": PASSWORD, "code": "000000"}).status_code == 422
    assert client.post("/api/auth/2fa/disable", json={"password": "Wrong-pass-9", "code": _fresh_code(secret)}).status_code == 403
    assert client.post("/api/auth/2fa/disable", json={"password": PASSWORD, "code": _fresh_code(secret)}).json()["enabled"] is False
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json().get("id")


def test_totp_secret_and_recovery_codes_never_in_api_responses(client):
    new_user(client)
    secret, codes = _enable_2fa(client)
    me = client.get("/api/auth/me").text + client.get("/api/auth/2fa").text
    assert secret not in me and codes[0] not in me

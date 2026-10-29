"""Encryption of two-step secrets, the 'two-step sign-in required' setting, and the administration API."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend import auth, mfa, secretbox
from backend.main import app

from conftest import PASSWORD, new_user


def _enable_2fa(c):
    secret = c.post("/api/auth/2fa/setup", json={"password": PASSWORD}).json()["secret"]
    codes = c.post("/api/auth/2fa/enable", json={"code": mfa.code_at(secret, mfa.current_step())}).json()["recovery_codes"]
    return secret, codes


def _stored(email):
    with sqlite3.connect(auth.DB_PATH) as c:
        return c.execute("SELECT totp_secret FROM users WHERE email=?", (email,)).fetchone()[0]


# ---------------------------------------------------------------- encryption at rest
def test_two_step_secret_is_encrypted_in_the_database(client):
    email = new_user(client)
    secret, _ = _enable_2fa(client)
    stored = _stored(email)
    assert stored.startswith("fernet:") and secret not in stored
    assert secretbox.decrypt(stored) == secret


def test_database_copy_without_the_key_reveals_nothing(client, monkeypatch):
    email = new_user(client)
    secret, codes = _enable_2fa(client)
    stored = _stored(email)
    monkeypatch.setenv("MOMO_SECRET_KEY", "a-completely-different-key-held-by-an-attacker")
    secretbox.reset_cache()
    try:
        assert secretbox.decrypt(stored) is None
        # with the wrong key the authenticator code cannot be checked, but recovery codes (hashes) still work
        client.post("/api/auth/logout")
        tok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["mfa_token"]
        assert client.post("/api/auth/login/2fa", json={"mfa_token": tok, "code": mfa.code_at(secret, mfa.current_step() + 1)}).status_code == 401
        tok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["mfa_token"]
        assert client.post("/api/auth/login/2fa", json={"mfa_token": tok, "code": codes[0]}).status_code == 200
    finally:
        monkeypatch.delenv("MOMO_SECRET_KEY")
        secretbox.reset_cache()


def test_secrets_stored_before_encryption_are_upgraded(client):
    email = new_user(client)
    secret, _ = _enable_2fa(client)
    with sqlite3.connect(auth.DB_PATH) as c:  # simulate an account from the previous version
        c.execute("UPDATE users SET totp_secret=?, totp_last_step=NULL WHERE email=?", (secret, email))
    client.post("/api/auth/logout")
    tok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["mfa_token"]
    assert client.post("/api/auth/login/2fa", json={"mfa_token": tok, "code": mfa.code_at(secret, mfa.current_step())}).status_code == 200
    assert _stored(email).startswith("fernet:")


def test_key_file_is_created_outside_the_database():
    import os
    secretbox.reset_cache()
    secretbox.encrypt("x")
    path = secretbox._key_file()
    assert os.path.exists(path) and path != auth.DB_PATH


# ---------------------------------------------------------------- two-step sign-in required
def test_required_two_step_blocks_everything_until_set_up(client, monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_2FA", True)
    new_user(client)
    assert client.get("/api/overview").status_code == 403
    assert client.get("/api/auth/config").json()["require_2fa"] is True
    assert client.get("/api/auth/me").status_code == 200          # may still see who they are
    _enable_2fa(client)                                             # and set it up
    assert client.get("/api/overview").status_code == 200


def test_required_two_step_also_blocks_api_keys(client, monkeypatch):
    new_user(client)
    key = client.post("/api/auth/api-key").json()["api_key"]
    monkeypatch.setattr(auth, "REQUIRE_2FA", True)
    with TestClient(app) as robot:
        assert robot.get("/api/overview", headers={"X-API-Key": key}).status_code == 403


# ---------------------------------------------------------------- administration
@pytest.fixture
def admin(client, monkeypatch):
    email = new_user(client, name="Akua Admin")
    monkeypatch.setattr(auth, "ADMIN_EMAILS", {email})
    _enable_2fa(client)
    client.email = email
    return client


def test_admin_needs_listing_and_two_step(client, monkeypatch):
    email = new_user(client)
    assert client.get("/api/admin/users").status_code == 403           # not listed
    monkeypatch.setattr(auth, "ADMIN_EMAILS", {email})
    r = client.get("/api/admin/users")
    assert r.status_code == 403 and "two-step" in r.json()["detail"]  # listed, but no 2FA yet


def test_admin_sees_accounts_but_never_secrets(admin):
    with TestClient(app) as other:
        new_user(other)
        other.post("/api/auth/api-key")
    users = admin.get("/api/admin/users").json()
    text = str(users)
    assert len(users) >= 2 and "password_hash" not in text and "totp_secret" not in text and "api_key_hash" not in text
    assert admin.get("/api/admin/summary").json()["users"] >= 2
    assert any(e["event"] == "register" for e in admin.get("/api/admin/events").json())


def test_admin_can_disable_and_enable_an_account(admin):
    with TestClient(app) as other:
        email = new_user(other)
        uid = other.get("/api/auth/me").json()["id"]
        assert admin.post(f"/api/admin/users/{uid}/disable").status_code == 200
        assert other.get("/api/auth/me").status_code == 401                       # signed out at once
        r = other.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 403 and "disabled" in r.json()["detail"]
        wrong = other.post("/api/auth/login", json={"email": email, "password": "Wrong-pass-1"})
        assert wrong.status_code == 401                                            # no hint without the password
        assert admin.post(f"/api/admin/users/{uid}/enable").status_code == 200
        assert other.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
        labels = [e["label"] for e in other.get("/api/auth/activity").json()]
        assert "Account disabled by an administrator" in labels


def test_admin_can_reset_someones_two_step(admin):
    with TestClient(app) as other:
        email = new_user(other)
        _enable_2fa(other)
        uid = other.get("/api/auth/me").json()["id"]
        assert admin.post(f"/api/admin/users/{uid}/reset-2fa").status_code == 200
        r = other.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()
        assert "mfa_required" not in r and r["mfa_enabled"] is False


def test_admin_cannot_act_on_self_and_actions_are_logged(admin):
    me = admin.get("/api/auth/me").json()["id"]
    assert admin.post(f"/api/admin/users/{me}/disable").status_code == 400
    with TestClient(app) as other:
        new_user(other)
        uid = other.get("/api/auth/me").json()["id"]
        admin.post(f"/api/admin/users/{uid}/signout")
        assert other.get("/api/auth/me").status_code == 401
    mine = admin.get("/api/auth/activity").json()
    assert any(e["event"] == "admin_action" and "Signed out everywhere" in (e["detail"] or "") for e in mine)


def test_admin_delete_removes_account(admin):
    with TestClient(app) as other:
        email = new_user(other)
        uid = other.get("/api/auth/me").json()["id"]
        assert admin.post(f"/api/admin/users/{uid}/delete").status_code == 200
        assert other.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401


def test_admin_api_refuses_api_keys(admin):
    key = admin.post("/api/auth/api-key").json()["api_key"]
    with TestClient(app) as robot:
        assert robot.get("/api/admin/users", headers={"X-API-Key": key}).status_code == 403

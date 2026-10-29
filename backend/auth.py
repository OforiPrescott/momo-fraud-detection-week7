"""
User accounts: registration, sign-in, sign-out, profile, password change and personal API keys.

Standard library only (sqlite3 + hashlib), so it adds nothing to install on any OS.
  * Passwords are stored as salted PBKDF2-SHA256 hashes, never in plain text.
  * A sign-in creates a random session token; the browser keeps it in an HttpOnly cookie
    (unreadable by page scripts) and the database keeps only its SHA-256 hash.
  * Each user can create a personal API key (sent as X-API-Key) so their own systems can
    push transactions to /api/ingest or call the analysis endpoints without a browser.
  * Repeated failed sign-ins from one address are slowed down (429) to stop password guessing.

The database lives at MOMO_DB_PATH (default: <project>/var/momo.db) and is created on first use.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.environ.get("MOMO_DB_PATH", os.path.join(HERE, "..", "var", "momo.db")))
COOKIE = "momo_session"
SECURE_COOKIES = os.environ.get("MOMO_SECURE_COOKIES", "0") == "1"   # set to 1 behind HTTPS
ALLOW_REGISTRATION = os.environ.get("MOMO_ALLOW_REGISTRATION", "1") == "1"
SHORT_SESSION, LONG_SESSION = 24 * 3600, 30 * 24 * 3600              # "remember me" keeps 30 days
PBKDF2_ITERATIONS = 600_000
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register", "/api/auth/config"}
ON_DELETE: list = []  # callbacks(user_id) that free a deleted user's in-memory data (set up by main.py)

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_init_lock = threading.Lock()
_ready = False


# ------------------------------------------------------------------ storage
@contextmanager
def _db():
    global _ready
    if not _ready:
        with _init_lock:
            if not _ready:
                os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
                with sqlite3.connect(DB_PATH) as c:
                    c.executescript("""
                        PRAGMA journal_mode=WAL;
                        CREATE TABLE IF NOT EXISTS users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                            name TEXT NOT NULL,
                            organization TEXT NOT NULL DEFAULT '',
                            password_hash TEXT NOT NULL,
                            api_key_hash TEXT,
                            api_key_hint TEXT,
                            created_at REAL NOT NULL,
                            last_login REAL);
                        CREATE TABLE IF NOT EXISTS auth_sessions (
                            token_hash TEXT PRIMARY KEY,
                            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            created_at REAL NOT NULL,
                            expires_at REAL NOT NULL);
                        CREATE INDEX IF NOT EXISTS ix_sessions_user ON auth_sessions(user_id);
                        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_key ON users(api_key_hash);
                    """)
                _ready = True
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        with con:
            yield con
    finally:
        con.close()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # equalises timing when the email does not exist


def _public(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "organization": row["organization"],
            "created_at": row["created_at"], "last_login": row["last_login"],
            "api_key_hint": row["api_key_hint"]}


# ------------------------------------------------------------------ validation + rate limiting
def _check_password(pw: str):
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(422, "Use at least 8 characters, with at least one letter and one number.")
    if len(pw) > 256:
        raise HTTPException(422, "Password is too long.")


def _clean_text(v: str, field: str, max_len: int, required=True) -> str:
    v = (v or "").strip()
    if required and not v:
        raise HTTPException(422, f"{field} is required.")
    if len(v) > max_len:
        raise HTTPException(422, f"{field} must be at most {max_len} characters.")
    return v


_fails: "dict[str, deque]" = defaultdict(deque)
_fails_lock = threading.Lock()
FAIL_WINDOW, FAIL_LIMIT = 15 * 60, 8


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttled(*keys) -> bool:
    now = time.time()
    with _fails_lock:
        for k in keys:
            q = _fails[k]
            while q and now - q[0] > FAIL_WINDOW:
                q.popleft()
            if len(q) >= FAIL_LIMIT:
                return True
    return False


def _record_fail(*keys):
    with _fails_lock:
        for k in keys:
            _fails[k].append(time.time())


# ------------------------------------------------------------------ sessions
def _start_session(response: Response, user_id: int, remember: bool):
    token = secrets.token_urlsafe(32)
    ttl = LONG_SESSION if remember else SHORT_SESSION
    now = time.time()
    with _db() as c:
        c.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
        c.execute("INSERT INTO auth_sessions VALUES (?,?,?,?)", (_sha(token), user_id, now, now + ttl))
        c.execute("UPDATE users SET last_login=? WHERE id=?", (now, user_id))
    response.set_cookie(COOKIE, token, max_age=ttl if remember else None, httponly=True, samesite="lax",
                        secure=SECURE_COOKIES, path="/")


def user_from_request(request: Request):
    """The signed-in user (session cookie or X-API-Key header), or None."""
    token = request.cookies.get(COOKIE)
    with _db() as c:
        if token:
            row = c.execute("""SELECT u.* FROM auth_sessions s JOIN users u ON u.id = s.user_id
                               WHERE s.token_hash=? AND s.expires_at > ?""", (_sha(token), time.time())).fetchone()
            if row:
                return _public(row)
        key = request.headers.get("x-api-key", "").strip()
        if key:
            row = c.execute("SELECT * FROM users WHERE api_key_hash=?", (_sha(key),)).fetchone()
            if row:
                return _public(row)
    return None


def guard(request: Request):
    """Applied to every route: everything under /api/ needs a signed-in user except the public paths."""
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC_PATHS:
        return
    user = user_from_request(request)
    if not user:
        raise HTTPException(401, "Please sign in to continue.")
    request.state.user = user


def current_user(request: Request) -> dict:
    return request.state.user


# ------------------------------------------------------------------ routes
router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    organization: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str
    remember: bool = True


class ProfileRequest(BaseModel):
    name: str
    organization: str = ""


class PasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ConfirmRequest(BaseModel):
    password: str


@router.get("/config")
def auth_config():
    return {"registration_open": ALLOW_REGISTRATION}


@router.post("/register")
def register(req: RegisterRequest, request: Request, response: Response):
    if not ALLOW_REGISTRATION:
        raise HTTPException(403, "New registrations are closed on this server.")
    if _throttled("reg:" + _client_ip(request)):
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    name = _clean_text(req.name, "Name", 80)
    org = _clean_text(req.organization, "Organisation", 120, required=False)
    email = req.email.strip().lower()
    if not _EMAIL.match(email) or len(email) > 254:
        raise HTTPException(422, "Enter a valid email address.")
    _check_password(req.password)
    try:
        with _db() as c:
            cur = c.execute("INSERT INTO users (email, name, organization, password_hash, created_at) VALUES (?,?,?,?,?)",
                            (email, name, org, hash_password(req.password), time.time()))
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        _record_fail("reg:" + _client_ip(request))
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    _start_session(response, uid, remember=True)
    with _db() as c:
        return _public(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response):
    email = req.email.strip().lower()
    keys = ("ip:" + _client_ip(request), "email:" + email)
    if _throttled(*keys):
        raise HTTPException(429, "Too many failed sign-in attempts. Wait 15 minutes and try again.")
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not verify_password(req.password, row["password_hash"] if row else _DUMMY_HASH) or not row:
        _record_fail(*keys)
        raise HTTPException(401, "Email or password is incorrect.")
    _start_session(response, row["id"], req.remember)
    return _public(row) | {"last_login": time.time()}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with _db() as c:
            c.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_sha(token),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response):
    with _db() as c:
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (current_user(request)["id"],))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return current_user(request)


@router.post("/profile")
def update_profile(req: ProfileRequest, request: Request):
    uid = current_user(request)["id"]
    name = _clean_text(req.name, "Name", 80)
    org = _clean_text(req.organization, "Organisation", 120, required=False)
    with _db() as c:
        c.execute("UPDATE users SET name=?, organization=? WHERE id=?", (name, org, uid))
        return _public(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


@router.post("/password")
def change_password(req: PasswordRequest, request: Request):
    uid = current_user(request)["id"]
    with _db() as c:
        row = c.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
        if not verify_password(req.current_password, row["password_hash"]):
            raise HTTPException(403, "Your current password is incorrect.")
        _check_password(req.new_password)
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(req.new_password), uid))
        # sign out every other browser; keep this one
        keep = _sha(request.cookies.get(COOKIE, ""))
        c.execute("DELETE FROM auth_sessions WHERE user_id=? AND token_hash<>?", (uid, keep))
    return {"ok": True}


@router.post("/api-key")
def create_api_key(request: Request):
    """Creates (or replaces) the user's personal API key. The full key is shown only once."""
    uid = current_user(request)["id"]
    key = "momo_" + secrets.token_urlsafe(24)
    with _db() as c:
        c.execute("UPDATE users SET api_key_hash=?, api_key_hint=? WHERE id=?", (_sha(key), key[-4:], uid))
    return {"api_key": key, "api_key_hint": key[-4:]}


@router.post("/api-key/revoke")
def revoke_api_key(request: Request):
    with _db() as c:
        c.execute("UPDATE users SET api_key_hash=NULL, api_key_hint=NULL WHERE id=?", (current_user(request)["id"],))
    return {"ok": True}


@router.post("/delete")
def delete_account(req: ConfirmRequest, request: Request, response: Response):
    uid = current_user(request)["id"]
    with _db() as c:
        row = c.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
        if not verify_password(req.password, row["password_hash"]):
            raise HTTPException(403, "Password is incorrect.")
        c.execute("DELETE FROM users WHERE id=?", (uid,))
    for cb in ON_DELETE:
        cb(uid)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

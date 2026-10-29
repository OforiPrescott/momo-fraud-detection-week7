"""
User accounts: registration, sign-in, sign-out, profile, password change, personal API keys and a
security activity log. Standard library only (sqlite3 + hashlib), so it adds nothing to install.

How credentials are stored (see SECURITY.md for the full picture):
  * Passwords: never stored. Only a salted PBKDF2-HMAC-SHA256 hash (600,000 iterations, 16-byte random
    salt per user) is kept. Hashes made with fewer iterations are upgraded at the next sign-in.
  * Sessions: a random 256-bit token lives in an HttpOnly, SameSite=Lax cookie (Secure behind HTTPS);
    the database keeps only its SHA-256 hash, so a stolen database cannot be replayed as sessions.
  * API keys: shown to the user once; only their SHA-256 hash and last 4 characters are stored.

  * Two-step sign-in (optional, per user): an authenticator-app secret (TOTP, see mfa.py) and 8 single-use
    recovery codes stored as SHA-256 hashes. With it on, a password alone never creates a session.
  * Password reset: a single-use, 30-minute link emailed to the account (mailer.py); only its hash is stored.

Defences: password policy with a common-password blocklist, timing-equalised sign-in, rate limiting of
sign-in / registration / password confirmation / reset requests / authenticator codes, an Origin check
against cross-site requests (CSRF), and an audit trail of security events that each user can see on their
Account page.

The database lives at MOMO_DB_PATH (default: <project>/var/momo.db) and is created on first use.
"""
import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import mailer, mfa, secretbox

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.environ.get("MOMO_DB_PATH", os.path.join(HERE, "..", "var", "momo.db")))
COOKIE = "momo_session"
SECURE_COOKIES = os.environ.get("MOMO_SECURE_COOKIES", "0") == "1"   # set to 1 behind HTTPS
ALLOW_REGISTRATION = os.environ.get("MOMO_ALLOW_REGISTRATION", "1") == "1"
# MOMO_REQUIRE_2FA=1: every account must turn on two-step sign-in before it can use anything else
REQUIRE_2FA = os.environ.get("MOMO_REQUIRE_2FA", "0") == "1"
# administrators are named by email (comma-separated); they get the Administration page once they use 2FA
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("MOMO_ADMIN_EMAILS", "").split(",") if e.strip()}
# what an account without two-step sign-in may still do when REQUIRE_2FA is on: set it up, or leave
SETUP_PATHS = {"/api/auth/me", "/api/auth/logout", "/api/auth/logout-all", "/api/auth/2fa", "/api/auth/2fa/setup",
               "/api/auth/2fa/enable", "/api/auth/activity", "/api/auth/config"}
# extra origins (scheme://host:port) allowed to send signed-in requests, e.g. a separately hosted frontend
TRUSTED_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("MOMO_TRUSTED_ORIGINS", "").split(",") if o.strip()}
SHORT_SESSION, LONG_SESSION = 24 * 3600, 30 * 24 * 3600              # "remember me" keeps 30 days
PBKDF2_ITERATIONS = 600_000                                          # OWASP 2023+ guidance for PBKDF2-SHA256
AUDIT_RETENTION = 90 * 24 * 3600
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register", "/api/auth/config",
                "/api/auth/forgot", "/api/auth/reset", "/api/auth/login/2fa"}
RESET_TTL = 30 * 60      # a password-reset link works for 30 minutes, once
MFA_TTL = 5 * 60         # after the password, the authenticator code must follow within 5 minutes
MFA_MAX_ATTEMPTS = 5     # wrong codes allowed per sign-in attempt
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ON_DELETE: list = []  # callbacks(user_id) that free a deleted user's in-memory data (set up by main.py)

log = logging.getLogger("momo.security")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_init_lock = threading.Lock()
_ready = False

# The most-used passwords that still pass the length/letter/number rule; rejected outright.
COMMON_PASSWORDS = {
    "password1", "password12", "password123", "password1234", "passw0rd", "p@ssw0rd", "p@ssword1",
    "qwerty123", "qwerty1234", "qwertyuiop1", "abc12345", "abcd1234", "abcdef123", "1q2w3e4r", "1qaz2wsx",
    "zaq12wsx", "iloveyou1", "welcome1", "welcome123", "letmein1", "admin123", "admin1234", "administrator1",
    "monkey123", "dragon123", "football1", "baseball1", "sunshine1", "princess1", "trustno1", "master123",
    "superman1", "batman123", "starwars1", "computer1", "michael1", "jesus123", "freedom1", "whatever1",
    "changeme1", "test1234", "testing123", "default1", "secret123", "summer2024", "summer2025", "winter2024",
    "spring2025", "autumn2025", "ghana123", "accra123", "momo1234", "mobilemoney1", "fraud123", "security1",
    "user1234", "login123", "hello123", "football123", "chelsea1", "arsenal1", "liverpool1", "manutd1",
    "a1b2c3d4", "aa123456", "asdf1234", "zxcvbnm1", "q1w2e3r4", "123qweasd", "1234qwer", "qwer1234",
}


# ------------------------------------------------------------------ storage
@contextmanager
def _db():
    global _ready
    if not _ready or not os.path.exists(DB_PATH):  # also rebuilds if the file is deleted while running
        with _init_lock:
            if not _ready or not os.path.exists(DB_PATH):
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
                        CREATE TABLE IF NOT EXISTS security_events (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                            event TEXT NOT NULL,
                            ip TEXT,
                            user_agent TEXT,
                            at REAL NOT NULL);
                        CREATE TABLE IF NOT EXISTS reset_tokens (
                            token_hash TEXT PRIMARY KEY,
                            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            expires_at REAL NOT NULL);
                        CREATE TABLE IF NOT EXISTS mfa_challenges (
                            token_hash TEXT PRIMARY KEY,
                            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            remember INTEGER NOT NULL,
                            attempts INTEGER NOT NULL DEFAULT 0,
                            expires_at REAL NOT NULL);
                        CREATE TABLE IF NOT EXISTS recovery_codes (
                            code_hash TEXT NOT NULL,
                            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            used_at REAL);
                        CREATE INDEX IF NOT EXISTS ix_sessions_user ON auth_sessions(user_id);
                        CREATE INDEX IF NOT EXISTS ix_events_user ON security_events(user_id, at);
                        CREATE INDEX IF NOT EXISTS ix_recovery_user ON recovery_codes(user_id);
                        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_key ON users(api_key_hash);
                    """)
                    # upgrade databases created by earlier versions (adds the two-step sign-in columns)
                    have = {r[1] for r in c.execute("PRAGMA table_info(users)")}
                    for col, ddl in (("totp_secret", "TEXT"), ("totp_pending", "TEXT"), ("totp_last_step", "INTEGER"),
                                     ("disabled_at", "REAL")):
                        if col not in have:
                            c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
                    if "detail" not in {r[1] for r in c.execute("PRAGMA table_info(security_events)")}:
                        c.execute("ALTER TABLE security_events ADD COLUMN detail TEXT")
                try:
                    os.chmod(DB_PATH, 0o600)  # owner read/write only (no effect on Windows ACLs)
                except OSError:
                    pass
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


def needs_rehash(stored: str) -> bool:
    try:
        return int(stored.split("$")[1]) < PBKDF2_ITERATIONS
    except (IndexError, ValueError):
        return True


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # equalises timing when the email does not exist


def _public(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "organization": row["organization"],
            "created_at": row["created_at"], "last_login": row["last_login"],
            "api_key_hint": row["api_key_hint"], "mfa_enabled": bool(row["totp_secret"]),
            "is_admin": row["email"].lower() in ADMIN_EMAILS}


# ------------------------------------------------------------------ audit trail
EVENT_LABELS = {
    "register": "Account created", "login": "Signed in", "login_failed": "Failed sign-in attempt",
    "login_throttled": "Sign-in paused after repeated failures", "logout": "Signed out",
    "logout_all": "Signed out of all devices", "password_changed": "Password changed",
    "password_failed": "Wrong current password entered", "profile_updated": "Profile updated",
    "api_key_created": "API key created", "api_key_revoked": "API key revoked",
    "password_reset_requested": "Password reset link requested", "password_reset": "Password reset by email link",
    "mfa_enabled": "Two-step sign-in turned on", "mfa_disabled": "Two-step sign-in turned off",
    "mfa_failed": "Wrong authenticator code entered", "recovery_code_used": "Recovery code used to sign in",
    "recovery_codes_regenerated": "New recovery codes created",
    "login_blocked": "Sign-in refused: account disabled", "account_disabled": "Account disabled by an administrator",
    "account_enabled": "Account re-enabled by an administrator",
    "mfa_reset_by_admin": "Two-step sign-in reset by an administrator",
    "signed_out_by_admin": "Signed out everywhere by an administrator", "admin_action": "Administrator action",
}


def _audit(request: Request, event: str, user_id=None, detail: str = ""):
    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:200]
    now = time.time()
    try:
        with _db() as c:
            c.execute("INSERT INTO security_events (user_id, event, ip, user_agent, at, detail) VALUES (?,?,?,?,?,?)",
                      (user_id, event, ip, ua, now, detail[:200] or None))
            c.execute("DELETE FROM security_events WHERE at < ?", (now - AUDIT_RETENTION,))
    except sqlite3.Error as e:  # auditing must never break sign-in
        log.error("audit write failed: %s", e)
    log.info("security event=%s user=%s ip=%s %s", event, user_id, ip, detail)


# ------------------------------------------------------------------ validation + rate limiting
def _check_password(pw: str, email: str = "", name: str = ""):
    if len(pw) > 256:
        raise HTTPException(422, "Password is too long (256 characters at most).")
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(422, "Use at least 8 characters, with at least one letter and one number.")
    low = pw.lower()
    if low in COMMON_PASSWORDS:
        raise HTTPException(422, "That password is too common and easy to guess. Choose another.")
    local = email.split("@")[0].lower() if email else ""
    if (len(local) >= 4 and local in low) or any(len(w) >= 4 and w.lower() in low for w in name.split()):
        raise HTTPException(422, "Your password must not contain your name or email address.")
    if len(set(low)) < 4:
        raise HTTPException(422, "That password repeats too few characters. Choose a less predictable one.")


def _clean_text(v: str, field: str, max_len: int, required=True) -> str:
    v = re.sub(r"[\x00-\x1f\x7f]", "", (v or "")).strip()  # no control characters in stored text
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


REGISTER_LIMIT = 30  # sign-ups per address per window: generous enough for a shared office or classroom network


def _throttled(*keys, limit: int = FAIL_LIMIT) -> bool:
    now = time.time()
    with _fails_lock:
        for k in keys:
            q = _fails[k]
            while q and now - q[0] > FAIL_WINDOW:
                q.popleft()
            if len(q) >= limit:
                return True
        if len(_fails) > 50_000:  # keep memory bounded under a flood of distinct keys
            for k in [k for k, q in _fails.items() if not q]:
                del _fails[k]
    return False


def _record_fail(*keys):
    with _fails_lock:
        for k in keys:
            _fails[k].append(time.time())


def _same_origin(request: Request) -> bool:
    """True when a browser request comes from this site (or a trusted one). Requests without Origin/Referer
    (scripts, curl, server-to-server) are not browser cross-site requests and pass."""
    src = request.headers.get("origin") or request.headers.get("referer")
    if not src or src == "null":
        return src is None
    p = urlparse(src)
    origin = f"{p.scheme}://{p.netloc}".rstrip("/")
    host = request.headers.get("host", "")
    return p.netloc == host or origin in TRUSTED_ORIGINS


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
                               WHERE s.token_hash=? AND s.expires_at > ? AND u.disabled_at IS NULL""",
                            (_sha(token), time.time())).fetchone()
            if row:
                return _public(row) | {"via": "session"}
        key = request.headers.get("x-api-key", "").strip()
        if key and len(key) <= 128:
            row = c.execute("SELECT * FROM users WHERE api_key_hash=? AND disabled_at IS NULL", (_sha(key),)).fetchone()
            if row:
                return _public(row) | {"via": "api_key"}
    return None


def guard(request: Request):
    """Applied to every route. Cross-site browser writes are refused (CSRF); everything under /api/ needs a
    signed-in user except the public paths."""
    path = request.url.path
    if not path.startswith("/api/"):
        return
    if request.method in UNSAFE_METHODS and not _same_origin(request):
        log.warning("blocked cross-site %s %s from %s", request.method, path, request.headers.get("origin"))
        raise HTTPException(403, "This request came from another website and was blocked.")
    if path in PUBLIC_PATHS:
        return
    user = user_from_request(request)
    if not user:
        raise HTTPException(401, "Please sign in to continue.")
    if REQUIRE_2FA and not user["mfa_enabled"] and path not in SETUP_PATHS:
        raise HTTPException(403, "This server requires two-step sign-in. Turn it on from your Account page to continue.")
    request.state.user = user


def current_user(request: Request) -> dict:
    return request.state.user


# ------------------------------------------------------------------ routes
router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str = Field(max_length=200)
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    organization: str = Field("", max_length=300)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    remember: bool = True


class ProfileRequest(BaseModel):
    name: str = Field(max_length=200)
    organization: str = Field("", max_length=300)


class PasswordRequest(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class ConfirmRequest(BaseModel):
    password: str = Field(max_length=256)


def _confirm_password(request: Request, uid: int, password: str, event_on_fail: str):
    """Re-checks the password for sensitive actions, with the same rate limit as sign-in."""
    key = f"confirm:{uid}"
    if _throttled(key):
        raise HTTPException(429, "Too many wrong passwords. Wait 15 minutes and try again.")
    with _db() as c:
        row = c.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        _record_fail(key)
        _audit(request, event_on_fail, uid)
        raise HTTPException(403, "Your password is incorrect.")


@router.get("/config")
def auth_config():
    return {"registration_open": ALLOW_REGISTRATION, "reset_by_email": mailer.configured(), "require_2fa": REQUIRE_2FA,
            "password_rules": "At least 8 characters with a letter and a number; not a common password; "
                              "must not contain your name or email."}


@router.post("/register")
def register(req: RegisterRequest, request: Request, response: Response):
    if not ALLOW_REGISTRATION:
        raise HTTPException(403, "New registrations are closed on this server.")
    ip_key = "reg:" + _client_ip(request)
    if _throttled(ip_key, limit=REGISTER_LIMIT):
        raise HTTPException(429, "Too many sign-up attempts from your network. Wait 15 minutes and try again.")
    _record_fail(ip_key)  # every attempt counts towards the per-address sign-up limit
    name = _clean_text(req.name, "Name", 80)
    org = _clean_text(req.organization, "Organisation", 120, required=False)
    email = req.email.strip().lower()
    if not _EMAIL.match(email) or len(email) > 254:
        raise HTTPException(422, "Enter a valid email address.")
    _check_password(req.password, email, name)
    try:
        with _db() as c:
            cur = c.execute("INSERT INTO users (email, name, organization, password_hash, created_at) VALUES (?,?,?,?,?)",
                            (email, name, org, hash_password(req.password), time.time()))
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists. Sign in instead.") from None
    _audit(request, "register", uid)
    _start_session(response, uid, remember=True)
    with _db() as c:
        return _public(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response):
    email = req.email.strip().lower()
    keys = ("ip:" + _client_ip(request), "email:" + email)
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if _throttled(*keys):
        _audit(request, "login_throttled", row["id"] if row else None)
        raise HTTPException(429, "Too many failed sign-in attempts. Wait 15 minutes and try again.")
    if not verify_password(req.password, row["password_hash"] if row else _DUMMY_HASH) or not row:
        _record_fail(*keys)
        _audit(request, "login_failed", row["id"] if row else None)
        raise HTTPException(401, "Email or password is incorrect.")
    if row["disabled_at"]:
        _audit(request, "login_blocked", row["id"])
        raise HTTPException(403, "This account has been disabled. Contact the person who runs this platform.")
    if needs_rehash(row["password_hash"]):  # transparently upgrade old, weaker hashes
        with _db() as c:
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(req.password), row["id"]))
    if row["totp_secret"]:  # two-step sign-in: the password alone does not create a session
        token = secrets.token_urlsafe(32)
        with _db() as c:
            c.execute("DELETE FROM mfa_challenges WHERE expires_at < ? OR user_id = ?", (time.time(), row["id"]))
            c.execute("INSERT INTO mfa_challenges (token_hash, user_id, remember, expires_at) VALUES (?,?,?,?)",
                      (_sha(token), row["id"], int(req.remember), time.time() + MFA_TTL))
        return {"mfa_required": True, "mfa_token": token}
    _start_session(response, row["id"], req.remember)
    _audit(request, "login", row["id"])
    return _public(row) | {"last_login": time.time()}


class MfaLoginRequest(BaseModel):
    mfa_token: str = Field(max_length=128)
    code: str = Field(max_length=32)


def _use_recovery_code(uid: int, code: str) -> bool:
    if not mfa.normalise_recovery(code):
        return False
    with _db() as c:
        cur = c.execute("UPDATE recovery_codes SET used_at=? WHERE user_id=? AND code_hash=? AND used_at IS NULL",
                        (time.time(), uid, mfa.recovery_hash(code)))
        return cur.rowcount == 1


def _secret_of(uid: int, stored):
    """Decrypts a stored authenticator secret; re-encrypts values saved before encryption existed."""
    plain = secretbox.decrypt(stored)
    if plain and not secretbox.is_encrypted(stored):
        with _db() as c:
            c.execute("UPDATE users SET totp_secret=? WHERE id=? AND totp_secret=?", (secretbox.encrypt(plain), uid, stored))
    return plain


def _use_totp(uid: int, stored_secret: str, last_step, code: str) -> bool:
    secret = _secret_of(uid, stored_secret)
    if not secret:  # key lost or data tampered: only recovery codes can work now
        log.error("two-step secret for user %s could not be decrypted (wrong MOMO_SECRET_KEY?)", uid)
        return False
    step = mfa.verify(secret, code, last_step)
    if step is None:
        return False
    with _db() as c:  # conditional update: two requests racing with the same code cannot both win
        cur = c.execute("UPDATE users SET totp_last_step=? WHERE id=? AND (totp_last_step IS NULL OR totp_last_step < ?)",
                        (step, uid, step))
        return cur.rowcount == 1


@router.post("/login/2fa")
def login_2fa(req: MfaLoginRequest, request: Request, response: Response):
    """Second step of sign-in: a code from the authenticator app, or one of the recovery codes."""
    with _db() as c:
        ch = c.execute("SELECT * FROM mfa_challenges WHERE token_hash=? AND expires_at > ?",
                       (_sha(req.mfa_token), time.time())).fetchone()
        row = c.execute("SELECT * FROM users WHERE id=?", (ch["user_id"],)).fetchone() if ch else None
    if not ch or not row or not row["totp_secret"] or row["disabled_at"]:
        raise HTTPException(401, "This sign-in has expired. Enter your email and password again.")
    uid = row["id"]
    if ch["attempts"] >= MFA_MAX_ATTEMPTS or _throttled(f"mfa:{uid}"):
        with _db() as c:
            c.execute("DELETE FROM mfa_challenges WHERE token_hash=?", (_sha(req.mfa_token),))
        raise HTTPException(429, "Too many wrong codes. Wait 15 minutes, then sign in again.")
    used_recovery = False
    if not _use_totp(uid, row["totp_secret"], row["totp_last_step"], req.code):
        used_recovery = _use_recovery_code(uid, req.code)
        if not used_recovery:
            with _db() as c:
                c.execute("UPDATE mfa_challenges SET attempts = attempts + 1 WHERE token_hash=?", (_sha(req.mfa_token),))
            _record_fail(f"mfa:{uid}")
            _audit(request, "mfa_failed", uid)
            raise HTTPException(401, "That code is not right. Check that your phone's clock is correct and try again.")
    with _db() as c:
        c.execute("DELETE FROM mfa_challenges WHERE token_hash=?", (_sha(req.mfa_token),))
    _start_session(response, uid, bool(ch["remember"]))
    _audit(request, "recovery_code_used" if used_recovery else "login", uid)
    return _public(row) | {"last_login": time.time()}


# ------------------------------------------------------------------ forgotten password
class ForgotRequest(BaseModel):
    email: str = Field(max_length=254)


class ResetRequest(BaseModel):
    token: str = Field(max_length=128)
    new_password: str = Field(max_length=256)


FORGOT_MESSAGE = ("If an account exists for that email, a reset link is on its way. It works once, within 30 minutes. "
                  "Check your spam folder if it does not arrive.")


@router.post("/forgot")
def forgot_password(req: ForgotRequest, request: Request):
    """Sends a single-use reset link. Answers the same way whether or not the email has an account."""
    email = req.email.strip().lower()
    keys = ("forgot-ip:" + _client_ip(request), "forgot:" + email)
    if _throttled(*keys, limit=5):
        raise HTTPException(429, "Too many reset requests. Wait 15 minutes and try again.")
    _record_fail(*keys)  # also stops anyone flooding a person's inbox with reset emails
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if row and not row["disabled_at"]:
        # links are built from MOMO_PUBLIC_URL, never from the request's Host header (which can be forged);
        # in console mode (no SMTP) the link only goes to the server log, so the request address is safe to use
        base = mailer.PUBLIC_URL or ("" if mailer.configured() else str(request.base_url).rstrip("/"))
        if not base:
            log.error("password reset not sent: set MOMO_PUBLIC_URL when MOMO_SMTP_HOST is configured")
        else:
            token = secrets.token_urlsafe(32)
            with _db() as c:
                c.execute("DELETE FROM reset_tokens WHERE user_id=? OR expires_at < ?", (row["id"], time.time()))
                c.execute("INSERT INTO reset_tokens VALUES (?,?,?)", (_sha(token), row["id"], time.time() + RESET_TTL))
            # the token travels after '#', so it is never sent to the server in logs or Referer headers
            mailer.send_password_reset(row["email"], row["name"], f"{base}/#reset={token}", RESET_TTL // 60)
            _audit(request, "password_reset_requested", row["id"])
    return {"ok": True, "message": FORGOT_MESSAGE}


@router.post("/reset")
def reset_password(req: ResetRequest, request: Request):
    ip_key = "reset:" + _client_ip(request)
    if _throttled(ip_key):
        raise HTTPException(429, "Too many attempts. Wait 15 minutes and ask for a new link.")
    with _db() as c:
        t = c.execute("SELECT * FROM reset_tokens WHERE token_hash=? AND expires_at > ?",
                      (_sha(req.token), time.time())).fetchone()
        row = c.execute("SELECT * FROM users WHERE id=?", (t["user_id"],)).fetchone() if t else None
    if not t or not row or row["disabled_at"]:
        _record_fail(ip_key)
        raise HTTPException(400, "This reset link is invalid, already used or expired. Ask for a new one.")
    _check_password(req.new_password, row["email"], row["name"])  # checked first, so a weak choice can be retried
    with _db() as c:
        if c.execute("DELETE FROM reset_tokens WHERE token_hash=?", (_sha(req.token),)).rowcount != 1:
            raise HTTPException(400, "This reset link is invalid, already used or expired. Ask for a new one.")
        c.execute("DELETE FROM reset_tokens WHERE user_id=?", (row["id"],))
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(req.new_password), row["id"]))
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (row["id"],))   # sign out everywhere
        c.execute("DELETE FROM mfa_challenges WHERE user_id=?", (row["id"],))
    _audit(request, "password_reset", row["id"])
    # no automatic sign-in: the person signs in with the new password (and their authenticator, if enabled)
    return {"ok": True, "mfa_enabled": bool(row["totp_secret"])}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with _db() as c:
            c.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_sha(token),))
    user = getattr(request.state, "user", None)
    if user:
        _audit(request, "logout", user["id"])
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/logout-all")
def logout_all(request: Request, response: Response):
    uid = current_user(request)["id"]
    with _db() as c:
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))
    _audit(request, "logout_all", uid)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return current_user(request)


@router.get("/activity")
def activity(request: Request):
    """The signed-in user's recent security events (last 90 days, newest first)."""
    uid = current_user(request)["id"]
    with _db() as c:
        rows = c.execute("SELECT event, ip, user_agent, at, detail FROM security_events WHERE user_id=? "
                         "ORDER BY at DESC LIMIT 25", (uid,)).fetchall()
    return [{"event": r["event"], "label": EVENT_LABELS.get(r["event"], r["event"]), "detail": r["detail"], "ip": r["ip"],
             "device": _device(r["user_agent"] or ""), "at": r["at"]} for r in rows]


def _device(ua: str) -> str:
    """A short, human description of a user agent ("Edge on Windows", "API client")."""
    if not ua:
        return "Unknown"
    browser = next((b for k, b in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
                                   ("Safari/", "Safari")) if k in ua), None)
    system = next((s for k, s in (("Windows", "Windows"), ("Mac OS X", "macOS"), ("Android", "Android"),
                                  ("iPhone", "iPhone"), ("iPad", "iPad"), ("Linux", "Linux")) if k in ua), None)
    if browser:
        return f"{browser} on {system}" if system else browser
    return "API client" if any(k in ua.lower() for k in ("curl", "python", "httpx", "postman", "testclient")) else ua[:40]


@router.post("/profile")
def update_profile(req: ProfileRequest, request: Request):
    uid = current_user(request)["id"]
    name = _clean_text(req.name, "Name", 80)
    org = _clean_text(req.organization, "Organisation", 120, required=False)
    with _db() as c:
        c.execute("UPDATE users SET name=?, organization=? WHERE id=?", (name, org, uid))
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    _audit(request, "profile_updated", uid)
    return _public(row)


@router.post("/password")
def change_password(req: PasswordRequest, request: Request):
    user = current_user(request)
    uid = user["id"]
    _confirm_password(request, uid, req.current_password, "password_failed")
    _check_password(req.new_password, user["email"], user["name"])
    if req.new_password == req.current_password:
        raise HTTPException(422, "Choose a password different from your current one.")
    with _db() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(req.new_password), uid))
        # sign out every other browser; keep this one. Outstanding reset links stop working too.
        keep = _sha(request.cookies.get(COOKIE, ""))
        c.execute("DELETE FROM auth_sessions WHERE user_id=? AND token_hash<>?", (uid, keep))
        c.execute("DELETE FROM reset_tokens WHERE user_id=?", (uid,))
    _audit(request, "password_changed", uid)
    return {"ok": True}


# ------------------------------------------------------------------ two-step sign-in management
class PasswordConfirm(BaseModel):
    password: str = Field(max_length=256)


class CodeRequest(BaseModel):
    code: str = Field(max_length=32)


class DisableMfaRequest(BaseModel):
    password: str = Field(max_length=256)
    code: str = Field(max_length=32)


def _browser_user(request: Request) -> dict:
    user = current_user(request)
    if user.get("via") != "session":
        raise HTTPException(403, "Two-step sign-in can only be changed from a signed-in browser session.")
    return user


@router.get("/2fa")
def mfa_status(request: Request):
    uid = current_user(request)["id"]
    with _db() as c:
        row = c.execute("SELECT totp_secret FROM users WHERE id=?", (uid,)).fetchone()
        left = c.execute("SELECT COUNT(*) FROM recovery_codes WHERE user_id=? AND used_at IS NULL", (uid,)).fetchone()[0]
    return {"enabled": bool(row["totp_secret"]), "recovery_codes_left": left}


@router.post("/2fa/setup")
def mfa_setup(req: PasswordConfirm, request: Request):
    """Step 1: confirm the password, get a new secret to scan. Nothing changes until /2fa/enable succeeds."""
    user = _browser_user(request)
    _confirm_password(request, user["id"], req.password, "password_failed")
    if user["mfa_enabled"]:
        raise HTTPException(409, "Two-step sign-in is already on. Turn it off first to set up a new phone.")
    secret = mfa.new_secret()
    with _db() as c:
        c.execute("UPDATE users SET totp_pending=? WHERE id=?", (secretbox.encrypt(secret), user["id"]))
    return {"secret": secret, "uri": mfa.provisioning_uri(secret, user["email"])}


@router.post("/2fa/enable")
def mfa_enable(req: CodeRequest, request: Request):
    """Step 2: prove the app works by entering its current code. Returns 8 recovery codes, shown once."""
    user = _browser_user(request)
    with _db() as c:
        pending = secretbox.decrypt(c.execute("SELECT totp_pending FROM users WHERE id=?", (user["id"],)).fetchone()["totp_pending"])
    if not pending:
        raise HTTPException(400, "Start the set-up again: no new key is waiting to be confirmed.")
    step = mfa.verify(pending, req.code, None)
    if step is None:
        _audit(request, "mfa_failed", user["id"])
        raise HTTPException(422, "That code is not right. Enter the 6 digits your app shows now.")
    codes = mfa.new_recovery_codes()
    with _db() as c:
        c.execute("UPDATE users SET totp_secret=?, totp_pending=NULL, totp_last_step=? WHERE id=?",
                  (secretbox.encrypt(pending), step, user["id"]))
        c.execute("DELETE FROM recovery_codes WHERE user_id=?", (user["id"],))
        c.executemany("INSERT INTO recovery_codes (code_hash, user_id) VALUES (?,?)",
                      [(mfa.recovery_hash(k), user["id"]) for k in codes])
    _audit(request, "mfa_enabled", user["id"])
    return {"enabled": True, "recovery_codes": codes}


@router.post("/2fa/disable")
def mfa_disable(req: DisableMfaRequest, request: Request):
    user = _browser_user(request)
    _confirm_password(request, user["id"], req.password, "password_failed")
    with _db() as c:
        row = c.execute("SELECT totp_secret, totp_last_step FROM users WHERE id=?", (user["id"],)).fetchone()
    if not row["totp_secret"]:
        return {"enabled": False}
    if not (_use_totp(user["id"], row["totp_secret"], row["totp_last_step"], req.code)
            or _use_recovery_code(user["id"], req.code)):
        _audit(request, "mfa_failed", user["id"])
        raise HTTPException(422, "That code is not right. Enter the code from your app, or a recovery code.")
    with _db() as c:
        c.execute("UPDATE users SET totp_secret=NULL, totp_pending=NULL, totp_last_step=NULL WHERE id=?", (user["id"],))
        c.execute("DELETE FROM recovery_codes WHERE user_id=?", (user["id"],))
    _audit(request, "mfa_disabled", user["id"])
    return {"enabled": False}


@router.post("/2fa/recovery-codes")
def mfa_new_recovery_codes(req: PasswordConfirm, request: Request):
    """Replaces all recovery codes (old ones stop working). Shown once."""
    user = _browser_user(request)
    _confirm_password(request, user["id"], req.password, "password_failed")
    if not user["mfa_enabled"]:
        raise HTTPException(400, "Turn on two-step sign-in first.")
    codes = mfa.new_recovery_codes()
    with _db() as c:
        c.execute("DELETE FROM recovery_codes WHERE user_id=?", (user["id"],))
        c.executemany("INSERT INTO recovery_codes (code_hash, user_id) VALUES (?,?)",
                      [(mfa.recovery_hash(k), user["id"]) for k in codes])
    _audit(request, "recovery_codes_regenerated", user["id"])
    return {"recovery_codes": codes}


@router.post("/api-key")
def create_api_key(request: Request):
    """Creates (or replaces) the user's personal API key. The full key is shown only once."""
    user = current_user(request)
    if user.get("via") != "session":
        raise HTTPException(403, "API keys can only be managed from a signed-in browser session.")
    key = "momo_" + secrets.token_urlsafe(24)
    with _db() as c:
        c.execute("UPDATE users SET api_key_hash=?, api_key_hint=? WHERE id=?", (_sha(key), key[-4:], user["id"]))
    _audit(request, "api_key_created", user["id"])
    return {"api_key": key, "api_key_hint": key[-4:]}


@router.post("/api-key/revoke")
def revoke_api_key(request: Request):
    uid = current_user(request)["id"]
    with _db() as c:
        c.execute("UPDATE users SET api_key_hash=NULL, api_key_hint=NULL WHERE id=?", (uid,))
    _audit(request, "api_key_revoked", uid)
    return {"ok": True}


@router.post("/delete")
def delete_account(req: ConfirmRequest, request: Request, response: Response):
    user = current_user(request)
    if user.get("via") != "session":
        raise HTTPException(403, "Accounts can only be deleted from a signed-in browser session.")
    uid = user["id"]
    _confirm_password(request, uid, req.password, "password_failed")
    with _db() as c:
        c.execute("DELETE FROM users WHERE id=?", (uid,))  # sessions and audit rows go with it (ON DELETE CASCADE)
    log.info("security event=account_deleted user=%s ip=%s", uid, _client_ip(request))
    for cb in ON_DELETE:
        cb(uid)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

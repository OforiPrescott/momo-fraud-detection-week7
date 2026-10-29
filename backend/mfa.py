"""
Two-step sign-in with an authenticator app: time-based one-time passwords (TOTP, RFC 6238), standard
library only. Works with Google Authenticator, Microsoft Authenticator, Authy, 1Password, Bitwarden, etc.

  * Secret: 160 random bits, shown once as a QR code / text key while setting up.
  * Code: 6 digits, a new one every 30 seconds; one step of clock drift either way is accepted.
  * Replay: a code (time step) that has been used once is refused afterwards.
  * Recovery codes: 8 single-use codes for when the phone is lost; only their SHA-256 hashes are stored.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS, PERIOD, WINDOW = 6, 30, 1
ISSUER = "MoMo Fraud Detection"
RECOVERY_COUNT = 8
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i: easy to read and type


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return f"{value:0{DIGITS}d}"


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def verify(secret: str, code: str, last_step: int | None, now: float | None = None):
    """Returns the matching time step, or None. Steps at or before last_step are refused (no replay)."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = current_step(now)
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    """The otpauth:// link an authenticator app reads from the QR code."""
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={PERIOD}"


def new_recovery_codes() -> list:
    return ["".join(secrets.choice(_ALPHABET) for _ in range(5)) + "-" +
            "".join(secrets.choice(_ALPHABET) for _ in range(5)) for _ in range(RECOVERY_COUNT)]


def normalise_recovery(code: str) -> str:
    raw = "".join(ch for ch in (code or "").lower() if ch.isalnum())
    return f"{raw[:5]}-{raw[5:]}" if len(raw) == 10 else ""


def recovery_hash(code: str) -> str:
    return hashlib.sha256(normalise_recovery(code).encode()).hexdigest()

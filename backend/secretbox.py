"""
Encryption at rest for secrets the server must be able to read back (two-step sign-in secrets).

Passwords, session tokens, API keys, recovery codes and reset links are only ever hashed. An authenticator
secret cannot be hashed, because the server needs it to compute the expected code, so it is encrypted with
Fernet (AES-128-CBC + HMAC-SHA256, from the audited `cryptography` package) under a key kept OUTSIDE the
database. A copy of momo.db on its own therefore reveals no secrets.

The key comes from, in order:
  1. MOMO_SECRET_KEY: any long random string, set as an environment variable (recommended on servers, so the
     key never sits on the same disk or in the same backup as the database);
  2. otherwise a key file, MOMO_SECRET_KEY_FILE or `secret.key` next to the database, created on first use
     with owner-only permissions.

If the key is lost, encrypted secrets cannot be read: affected users sign in with a recovery code and set
two-step sign-in up again, or an administrator resets it. Values stored before encryption existed
(plain text) are still read, and re-encrypted the next time they are used.
"""
import base64
import hashlib
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "fernet:"
_lock = threading.Lock()
_fernet = None


def _key_file() -> str:
    from .auth import DB_PATH  # the key file lives next to the database unless configured otherwise
    return os.path.abspath(os.environ.get("MOMO_SECRET_KEY_FILE", os.path.join(os.path.dirname(DB_PATH), "secret.key")))


def _load() -> Fernet:
    global _fernet
    with _lock:
        if _fernet is None:
            env = os.environ.get("MOMO_SECRET_KEY", "").strip()
            if env:  # derive a proper 32-byte Fernet key from whatever string the operator chose
                key = base64.urlsafe_b64encode(hashlib.sha256(env.encode()).digest())
            else:
                path = _key_file()
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        key = f.read().strip()
                else:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    key = Fernet.generate_key()
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(key + b"\n")
            _fernet = Fernet(key)
        return _fernet


def reset_cache():
    """For tests and key rotation: forget the loaded key."""
    global _fernet
    with _lock:
        _fernet = None


def encrypt(value: str) -> str:
    return PREFIX + _load().encrypt(value.encode()).decode()


def decrypt(stored):
    """The plain value, or None if it cannot be decrypted (wrong or lost key, tampered data)."""
    if not stored:
        return None
    if not stored.startswith(PREFIX):
        return stored  # written before encryption existed
    try:
        return _load().decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return None


def is_encrypted(stored) -> bool:
    return bool(stored) and stored.startswith(PREFIX)

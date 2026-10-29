"""
Administration: account oversight for the people who run the platform.

Who is an administrator: accounts whose email is listed in MOMO_ADMIN_EMAILS (comma-separated). There is no
"first user becomes admin" rule, so a stranger who signs up early cannot take over a public server.
Every admin endpoint additionally requires a signed-in browser session (not an API key) with two-step
sign-in turned on, so a stolen admin password alone is not enough.

What an administrator can do: see every account (never its password or secrets), platform security
counts and recent security events, and for another account: disable or re-enable it, sign it out
everywhere, reset its two-step sign-in (for someone who lost both phone and recovery codes) or delete it.
Every action is recorded in the security log of both the administrator and the affected account.
"""
import time

from fastapi import APIRouter, HTTPException, Query, Request

from . import auth

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _admin(request: Request) -> dict:
    user = auth.current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(403, "Administrators only.")
    if user.get("via") != "session":
        raise HTTPException(403, "Administration is only available from a signed-in browser session.")
    if not user.get("mfa_enabled"):
        raise HTTPException(403, "Turn on two-step sign-in on your Account page before using administration.")
    return user


def _target(admin: dict, uid: int):
    if uid == admin["id"]:
        raise HTTPException(400, "Use your own Account page to change your own account.")
    with auth._db() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(404, "No such account.")
    return row


def _record(request: Request, admin: dict, row, event: str, what: str):
    auth._audit(request, event, row["id"], f"by {admin['email']}")
    auth._audit(request, "admin_action", admin["id"], f"{what}: {row['email']}")


@router.get("/summary")
def summary(request: Request):
    _admin(request)
    day = time.time() - 24 * 3600
    with auth._db() as c:
        q = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
        users = q("SELECT COUNT(*) FROM users")
        return {
            "users": users,
            "with_2fa": q("SELECT COUNT(*) FROM users WHERE totp_secret IS NOT NULL"),
            "disabled": q("SELECT COUNT(*) FROM users WHERE disabled_at IS NOT NULL"),
            "new_24h": q("SELECT COUNT(*) FROM users WHERE created_at > ?", day),
            "signins_24h": q("SELECT COUNT(*) FROM security_events WHERE event='login' AND at > ?", day),
            "failed_24h": q("SELECT COUNT(*) FROM security_events WHERE event IN ('login_failed','mfa_failed') AND at > ?", day),
            "throttled_24h": q("SELECT COUNT(*) FROM security_events WHERE event='login_throttled' AND at > ?", day),
            "require_2fa": auth.REQUIRE_2FA,
        }


@router.get("/users")
def users(request: Request):
    _admin(request)
    now, day = time.time(), time.time() - 24 * 3600
    with auth._db() as c:
        rows = c.execute("""
            SELECT u.*,
                   (SELECT COUNT(*) FROM auth_sessions s WHERE s.user_id = u.id AND s.expires_at > ?) AS sessions,
                   (SELECT COUNT(*) FROM security_events e WHERE e.user_id = u.id
                        AND e.event IN ('login_failed','mfa_failed') AND e.at > ?) AS failed_24h
            FROM users u ORDER BY u.created_at DESC""", (now, day)).fetchall()
    return [{"id": r["id"], "name": r["name"], "email": r["email"], "organization": r["organization"],
             "created_at": r["created_at"], "last_login": r["last_login"], "mfa_enabled": bool(r["totp_secret"]),
             "has_api_key": bool(r["api_key_hash"]), "disabled": bool(r["disabled_at"]),
             "is_admin": r["email"].lower() in auth.ADMIN_EMAILS, "sessions": r["sessions"],
             "failed_24h": r["failed_24h"]} for r in rows]


@router.get("/events")
def events(request: Request, limit: int = Query(100, ge=1, le=500)):
    """Recent security events across the platform, newest first (failed sign-ins for unknown emails included)."""
    _admin(request)
    with auth._db() as c:
        rows = c.execute("""SELECT e.*, u.email FROM security_events e LEFT JOIN users u ON u.id = e.user_id
                            ORDER BY e.at DESC LIMIT ?""", (limit,)).fetchall()
    return [{"at": r["at"], "event": r["event"], "label": auth.EVENT_LABELS.get(r["event"], r["event"]),
             "detail": r["detail"], "account": r["email"] or "(no such account)", "ip": r["ip"],
             "device": auth._device(r["user_agent"] or "")} for r in rows]


@router.post("/users/{uid}/disable")
def disable(uid: int, request: Request):
    admin = _admin(request)
    row = _target(admin, uid)
    with auth._db() as c:
        c.execute("UPDATE users SET disabled_at=? WHERE id=?", (time.time(), uid))
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))   # signed out immediately
        c.execute("DELETE FROM mfa_challenges WHERE user_id=?", (uid,))
        c.execute("DELETE FROM reset_tokens WHERE user_id=?", (uid,))
    _record(request, admin, row, "account_disabled", "Disabled account")
    return {"ok": True}


@router.post("/users/{uid}/enable")
def enable(uid: int, request: Request):
    admin = _admin(request)
    row = _target(admin, uid)
    with auth._db() as c:
        c.execute("UPDATE users SET disabled_at=NULL WHERE id=?", (uid,))
    _record(request, admin, row, "account_enabled", "Re-enabled account")
    return {"ok": True}


@router.post("/users/{uid}/signout")
def sign_out(uid: int, request: Request):
    admin = _admin(request)
    row = _target(admin, uid)
    with auth._db() as c:
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))
    _record(request, admin, row, "signed_out_by_admin", "Signed out everywhere")
    return {"ok": True}


@router.post("/users/{uid}/reset-2fa")
def reset_two_step(uid: int, request: Request):
    """For someone who lost both their phone and their recovery codes. Their sessions end too, so the next
    sign-in is with the password only, after which they should set two-step sign-in up again."""
    admin = _admin(request)
    row = _target(admin, uid)
    with auth._db() as c:
        c.execute("UPDATE users SET totp_secret=NULL, totp_pending=NULL, totp_last_step=NULL WHERE id=?", (uid,))
        c.execute("DELETE FROM recovery_codes WHERE user_id=?", (uid,))
        c.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))
    _record(request, admin, row, "mfa_reset_by_admin", "Reset two-step sign-in")
    return {"ok": True}


@router.post("/users/{uid}/delete")
def delete(uid: int, request: Request):
    admin = _admin(request)
    row = _target(admin, uid)
    auth._audit(request, "admin_action", admin["id"], f"Deleted account: {row['email']}")
    with auth._db() as c:
        c.execute("DELETE FROM users WHERE id=?", (uid,))
    for cb in auth.ON_DELETE:
        cb(uid)
    return {"ok": True}

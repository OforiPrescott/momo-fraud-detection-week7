"""
Outgoing email (password-reset links). Standard library only (smtplib).

Configure with environment variables:
  MOMO_SMTP_HOST      e.g. smtp.gmail.com, smtp.office365.com, or your provider's SMTP relay
  MOMO_SMTP_PORT      587 (STARTTLS, default) or 465 (TLS)
  MOMO_SMTP_USER      login for the SMTP server
  MOMO_SMTP_PASSWORD  its password / app password
  MOMO_SMTP_FROM      sender address shown to users (defaults to MOMO_SMTP_USER)
  MOMO_PUBLIC_URL     the address users open the platform at, e.g. https://momo.example.org
                      (required with SMTP: reset links are never built from the request's Host header,
                      which an attacker could forge to send people a link to their own site)

Without MOMO_SMTP_HOST the platform runs in "console mode": instead of emailing, the reset link is
written to the server log, so the person running the server can pass it on. Fine for a laptop or a
classroom; configure SMTP before inviting the public.
"""
import logging
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage

log = logging.getLogger("momo.mail")

HOST = os.environ.get("MOMO_SMTP_HOST", "").strip()
PORT = int(os.environ.get("MOMO_SMTP_PORT", "587"))
USER = os.environ.get("MOMO_SMTP_USER", "")
PASSWORD = os.environ.get("MOMO_SMTP_PASSWORD", "")
SENDER = os.environ.get("MOMO_SMTP_FROM", "") or USER
PUBLIC_URL = os.environ.get("MOMO_PUBLIC_URL", "").strip().rstrip("/")


def configured() -> bool:
    return bool(HOST)


def _send(to: str, subject: str, text: str):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = SENDER, to, subject
    msg.set_content(text)
    ctx = ssl.create_default_context()
    try:
        if PORT == 465:
            with smtplib.SMTP_SSL(HOST, PORT, context=ctx, timeout=15) as s:
                if USER:
                    s.login(USER, PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(HOST, PORT, timeout=15) as s:
                s.starttls(context=ctx)
                if USER:
                    s.login(USER, PASSWORD)
                s.send_message(msg)
        log.info("password-reset email sent to %s", to)
    except Exception as e:  # never crash a request because mail is down; the operator sees the error
        log.error("could not send email to %s: %s", to, e)


def send_password_reset(to: str, name: str, link: str, minutes: int):
    text = (f"Hello {name},\n\n"
            "Someone (hopefully you) asked to reset the password of your MoMo Fraud & Intrusion Detection "
            f"account. Open this link within {minutes} minutes to choose a new password:\n\n{link}\n\n"
            "The link works once. If you did not ask for this, ignore this email: your password stays the same. "
            "If it keeps happening, sign in and check Recent security activity on your Account page.\n")
    if not configured():
        log.warning("CONSOLE MODE (no MOMO_SMTP_HOST): password-reset link for %s -> %s", to, link)
        return
    # sent in the background so the response takes the same time whether or not the account exists
    threading.Thread(target=_send, args=(to, "Reset your MoMo Fraud Detection password", text), daemon=True).start()

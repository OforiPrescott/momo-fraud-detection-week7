"""
HTTP hardening applied to every response, plus helpers shared by the routes.

  * Content-Security-Policy: the dashboard may load scripts, styles, fonts and data only from this
    server, cannot be framed by another site (clickjacking) and cannot post forms elsewhere.
  * X-Content-Type-Options, Referrer-Policy, Permissions-Policy, Cross-Origin-Opener-Policy: browser
    defaults tightened.
  * Strict-Transport-Security when the site runs behind HTTPS (MOMO_SECURE_COOKIES=1).
  * API responses are marked no-store so shared computers and proxies never cache account data.

Written as a plain ASGI middleware (not BaseHTTPMiddleware) so the live Server-Sent Events stream is
passed through untouched.
"""
import os

from starlette.datastructures import MutableHeaders

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
# the interactive API docs load Swagger UI from a CDN, so they get a looser policy of their own
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
            "frame-ancestors 'none'")
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
HSTS = os.environ.get("MOMO_SECURE_COOKIES", "0") == "1"


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["Content-Security-Policy"] = DOCS_CSP if path.startswith(DOCS_PATHS) else CSP
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "strict-origin-when-cross-origin"
                h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
                h["Cross-Origin-Opener-Policy"] = "same-origin"
                if HSTS:
                    h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                if path.startswith("/api/") and "cache-control" not in h:
                    h["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralises spreadsheet formula injection: a text cell such as '=HYPERLINK(...)' in an exported CSV
    would run as a formula when opened in Excel. Prefixing a quote makes it plain text."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value

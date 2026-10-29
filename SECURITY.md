# Security

This document explains how the MoMo Fraud & Intrusion Detection platform protects the people who sign up
to it, the data they analyse and the model itself. Every control listed here is checked by an automated
test in `tests/test_security.py` or `tests/test_account_recovery.py`, which run on every push (see `.github/workflows/ci.yml`).

## 1. How your credentials are stored

**Your password is never stored, in any form that can be turned back into the password.**

| What | What is stored | How |
| --- | --- | --- |
| Password | A one-way hash only | PBKDF2-HMAC-SHA256, **600,000 iterations** (the OWASP recommendation for this algorithm), with a **unique random 16-byte salt per user**. Two users with the same password get completely different hashes. |
| Session (staying signed in) | SHA-256 hash of a random token | A 256-bit random token is placed in your browser in a cookie marked **HttpOnly** (page scripts cannot read it) and **SameSite=Lax** (not sent on cross-site requests), and **Secure** when the site runs over HTTPS. The database holds only the token's hash, so a copy of the database cannot be used to impersonate anyone. |
| API key | SHA-256 hash + last 4 characters | The full key is shown once, when created. It cannot be recovered afterwards, only replaced. |
| Two-step sign-in secret | The authenticator secret | A 160-bit random secret shared with your authenticator app. It has to be kept in a usable form to check your codes, so it is never shown again, never returned by the API, and protected with the database file (see section 6). |
| Recovery codes | SHA-256 hashes | 8 single-use codes shown once when two-step sign-in is turned on. |
| Password-reset link | SHA-256 hash of the token | A 256-bit random token, valid for 30 minutes and for one use only. |
| Name, email, organisation | Plain text | Needed to show your profile. Control characters are stripped and lengths are limited. |
| Uploaded transaction data | **Nothing** | Files are analysed in memory and never written to disk. They disappear when the server restarts. |

Hash format, as stored: `pbkdf2_sha256$600000$<salt>$<hash>`. If the iteration count is raised in a later
version, each user's hash is upgraded automatically the next time they sign in.

All of this lives in one SQLite file, `var/momo.db` (path set by `MOMO_DB_PATH`). It is excluded from Git,
created with owner-only file permissions on macOS and Linux, and can never be read through the platform's
own database connector.

## 2. Account protections

- **Password policy.** At least 8 characters with a letter and a number; rejects the most common passwords,
  passwords that contain your name or email, and passwords made of very few distinct characters.
- **Brute-force protection.** After 8 failed sign-ins in 15 minutes from one network address, or for one
  email, sign-in is paused for 15 minutes. The same limit protects the password re-checks for changing a
  password and deleting an account. Sign-ups are limited to 30 per network address per 15 minutes.
- **No account enumeration on sign-in.** A wrong email and a wrong password give the same message and take
  the same time to answer (a dummy hash is computed when the email does not exist).
- **Two-step sign-in (optional, recommended).** Each user can require a 6-digit code from an authenticator
  app (Google Authenticator, Microsoft Authenticator, Authy and others; TOTP, RFC 6238) on top of their
  password. With it on, a correct password alone never creates a session: it opens a 5-minute challenge that
  allows 5 wrong codes. Codes cannot be replayed, one 30-second step of clock drift is tolerated, and 8
  single-use recovery codes cover a lost phone. Turning it off needs both the password and a current code.
- **Forgotten password.** "Forgot password?" emails a single-use link valid for 30 minutes. The answer is
  identical whether or not the email has an account, requests are limited to 5 per email and per network
  address per 15 minutes (so nobody can flood an inbox), the link is built from `MOMO_PUBLIC_URL` and never
  from the request's Host header (which an attacker could forge), and the token travels after `#` so it never
  appears in server logs or Referer headers. Using it ends every session, invalidates other links, and does
  **not** skip two-step sign-in.
- **Session control.** Sessions last 24 hours, or 30 days with "Keep me signed in". Changing your password
  signs out every other device. "Sign out of all devices" ends every session at once.
- **Security activity log.** Sign-ins, failed attempts, password changes, API key changes and sign-outs are
  recorded with time, device and network address, kept for 90 days, and shown to each user on their Account
  page so they can spot activity that was not theirs.
- **Sensitive actions need a browser session.** API keys can be created and accounts deleted only from a
  signed-in browser, never with an API key alone.

## 3. Application protections

| Threat | Protection |
| --- | --- |
| Using the API without an account | Every `/api/` route except health and sign-in requires a session or API key. |
| One user seeing another's data | Analyses, exports, live feeds and replays are tied to the user who created them; other users get "not found". |
| Cross-site request forgery (CSRF) | SameSite cookies, plus every state-changing browser request must come from the platform's own origin. Requests from other websites are refused (403). |
| Cross-origin reading of data | No CORS by default: other websites cannot call the API from a browser. `MOMO_CORS_ORIGINS` opens it to named sites only. |
| Cross-site scripting (XSS) | React escapes all text; a strict Content-Security-Policy allows scripts only from the platform itself. |
| Clickjacking | `frame-ancestors 'none'` and `X-Frame-Options: DENY`. |
| Caching of private data | API responses are sent with `Cache-Control: no-store`. |
| Downgrade to plain HTTP | `Strict-Transport-Security` when `MOMO_SECURE_COOKIES=1` (set it once HTTPS is in place). |
| Oversized or malicious uploads | Size limit (300 MB), row limit (1 million), compressed files limited to 4x the upload size when expanded (blocks "zip bombs"), one file per zip, Excel parsed with `defusedxml` (blocks XML bombs). |
| Spreadsheet formula injection | Exported CSV cells that start with `=`, `+`, `-` or `@` are prefixed so Excel shows them as text. |
| SQL injection via the database connector | Only one `SELECT` is accepted; write keywords and `;` are refused; PostgreSQL/MySQL sessions are opened read-only; table names are validated. |
| Server-side request forgery (SSRF) via the API connector | Only `http`/`https`; cloud metadata and link-local addresses always blocked; internal networks blocked on shared servers (`MOMO_ALLOW_PRIVATE_HOSTS=0`); the address actually connected to is re-checked (defeats DNS rebinding); redirects are not followed; responses are size-capped while downloading. |
| Reading files on the server | The SQLite connector can be switched off (`MOMO_ALLOW_SERVER_FILES=0`) and can never open the account database. |
| Oversized form fields | Every request field has a maximum length. |

## 4. Machine-learning protections

- **Model integrity.** The model file is a Python pickle, and loading a pickle can run code. The server
  therefore loads `backend/model.joblib` only if its SHA-256 matches `backend/model.joblib.sha256` (or
  `MOMO_MODEL_SHA256`). A swapped or corrupted model is refused, not executed. The training scripts write
  the checksum whenever they save a model.
- **Input cleaning.** Non-numeric amounts are skipped, negative amounts are scored by their size, and
  infinite or out-of-range values are neutralised. Every correction is reported on the Data quality tab.
- **Data drift detection.** Each analysis measures how far the data is from what the model was trained on
  (Population Stability Index per input) and warns when scores may be less reliable. See `MODEL_CARD.md`.
- **Explainability.** Every flagged transaction shows the model's own reasons (TreeSHAP), so a decision can
  be checked by a person before money is held.

## 5. Running it safely for other people

1. Serve it over **HTTPS** (for example behind Caddy or Nginx), then set `MOMO_SECURE_COOKIES=1`.
2. Use `docker compose up --build -d`. The container runs as an unprivileged user, and `docker-compose.yml`
   already sets `MOMO_ALLOW_PRIVATE_HOSTS=0` and `MOMO_ALLOW_SERVER_FILES=0`.
3. Set `MOMO_ALLOW_REGISTRATION=0` once your users have signed up, if the platform is not meant to be open.
4. Set `MOMO_API_DOCS=0` to hide the interactive API documentation if you do not need it.
5. Configure email so "Forgot password?" works: `MOMO_SMTP_HOST`, `MOMO_SMTP_PORT` (587 or 465),
   `MOMO_SMTP_USER`, `MOMO_SMTP_PASSWORD`, `MOMO_SMTP_FROM`, and **`MOMO_PUBLIC_URL`** (the address users
   open, e.g. `https://momo.example.org`; reset emails are not sent without it). Without SMTP the platform runs
   in console mode: reset links are written to the server log for the operator to pass on.
6. Encourage everyone, and especially anyone handling real customer data, to turn on two-step sign-in.
7. Back up the accounts database regularly and keep the copy private. Without Docker: copy `var/momo.db`
   while the server is stopped. With Docker: `docker compose cp momo-fraud-detection:/app/var/momo.db ./momo-backup.db`.
8. Run `pip-audit -r requirements.txt` and `npm audit` (in `frontend/`) from time to time to check
   dependencies for known vulnerabilities (CI runs pip-audit on every push).

## 6. Known limitations

- Two-step sign-in secrets must be readable by the server to check codes, so they are stored as issued, not
  hashed. Anyone holding a copy of `var/momo.db` could generate codes for users who also lose their password.
  Keep the database and its backups private (file permissions, encrypted disk or volume).
- Two-step sign-in is optional per user; there is no setting yet that forces it for everyone.
- In console mode (no SMTP), reset links appear in the server log; protect that log like a password.
- Rate limits are kept in memory per server process; behind several server processes, also rate-limit at
  the reverse proxy.
- The REST API connector re-checks the connected address before reading a response, but the request itself
  has already been sent by then. Keep `MOMO_ALLOW_PRIVATE_HOSTS=0` on shared servers.
- Analyses are held in memory only, so they are lost on restart (this is also a privacy feature).

## 7. Reporting a vulnerability

Please do not open a public issue. Contact the repository owner privately with the steps to reproduce,
and allow time for a fix before disclosure.

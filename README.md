# ML-Based Intrusion and Fraud Detection System for Mobile Money Platforms in Ghana

Fraud detection system for mobile money platforms. Build-focused: implementation covering Weeks 1-7 of the roadmap.

## Architecture

1. **Data layer** (Python) — PaySim transaction backbone + a synthetic access-event
   layer (device ID, login timestamp, geolocation, SIM-change events),
   joined on account ID.
2. **Attack labeling layer** (Python) — Ghana-specific attack patterns:
   SIM-swap takeover, PIN-sharing abuse, agent collusion, layered on top
   of PaySim's own `isFraud` label.
3. **Feature engineering layer** (Python) — velocity, device/location
   change, and time-of-day features, built without leaking the Week 3
   rule outputs into the model's inputs.
4. **Detection layer** (Python, XGBoost + MLP) — a tuned XGBoost model and
   an MLP neural net, trained and compared on the same held-out test set.
5. **Presentation layer** (Python API + React frontend, Week 8) — a FastAPI
   backend that scores uploaded files, database tables and API feeds, scores
   live transactions as they arrive, and writes plain-language findings and
   recommendations automatically; consumed by a React SOC-analyst dashboard.

### Why two languages

The data science and modeling side (layers 1-4) is Python, the standard
choice for pandas/scikit-learn/XGBoost work. The presentation layer
splits into a Python backend (FastAPI, reusing the same trained model
objects directly) and a JavaScript frontend (a browser dashboard is what
a SOC analyst would actually use day to day). This is the conventional
architecture for this kind of product: a Python/data-science backend
behind an HTTP API, with a separate frontend client.

## Data note

Kaggle isn't reachable from the dev sandbox this was scaffolded in, so
`data/raw/paysim_synthetic.csv` was generated from the official PaySim
simulator's own calibration parameters, and is kept for quick dev runs.
**The real Kaggle PaySim1 CSV (`ealaxi/paysim1`) is what every result in
this README was run against** (`data/raw/paysim_real.csv`, 6,362,620
transactions).

## Quick start: run the dashboard (no dataset download needed)

The trained model (`backend/model.joblib`), the precomputed dashboard data (`backend/data/`),
the results (`reports/`) and the built dashboard (`frontend/dist/`) are all in the repo, so
Python is the only requirement. Node and the Kaggle data are only needed to change the UI or
retrain the model.

**macOS (Intel or Apple Silicon) / Linux** — one command does everything (creates `venv`, installs packages,
installs `libomp` for XGBoost on macOS, starts the server and opens the browser):

```bash
git clone https://github.com/OforiPrescott/momo-fraud-detection-week7.git
cd momo-fraud-detection-week7
./start.sh
```

It needs Python 3.11–3.13 (3.12 recommended). macOS's built-in `python3` is usually too old; the script
tells you if so. Install 3.12 with `brew install python@3.12`, or the "macOS 64-bit universal2" installer
from [python.org](https://www.python.org/downloads/macos/), which runs natively on Intel Macs. On macOS,
XGBoost also needs `libomp`; the script installs it through [Homebrew](https://brew.sh)
(`brew install libomp`), so install Homebrew first if you don't have it.

**Windows** — double-click `start.bat` (or run it from a terminal). Same steps, then opens the browser.

**By hand (any OS)**

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
uvicorn backend.main:app --port 8000
```

**Docker** (no Python needed; works on Intel Macs): `docker compose up --build`.

Then open http://localhost:8000 and **create an account** on the sign-in page. Every visitor registers
their own account; their analyses and live monitor are private to them.

### Accounts, security and trust

* Register, sign in (optionally "keep me signed in for 30 days"), sign out, sign out of all devices,
  edit profile, change password and delete the account, all from the dashboard (**Account** page).
* **Forgot password?** emails a single-use reset link valid for 30 minutes (configure SMTP, below; without
  it the link is printed in the server window). **Two-step sign-in** adds a 6-digit code from an
  authenticator app (Google/Microsoft Authenticator, Authy...) plus 8 one-time recovery codes; its secrets are
  encrypted at rest, and `MOMO_REQUIRE_2FA=1` makes it compulsory. Accounts listed in `MOMO_ADMIN_EMAILS` get an
  **Administration** page (accounts, security events, disable/re-enable, reset two-step, sign out, delete).
* **Passwords are never stored**: only a salted PBKDF2-SHA256 hash (600,000 iterations). Sessions and API
  keys are stored only as SHA-256 hashes. Weak and common passwords are refused; repeated failed sign-ins
  are paused; every sign-in, failure and key change appears in the user's **Recent security activity**.
* Every `/api/` route except health and sign-in requires an account, and each user's analyses and live
  monitor are private to them. Cross-site requests are refused, strict security headers are sent, uploads
  and connectors are size- and address-limited, and exported CSVs cannot run spreadsheet formulas.
* The model loads only if its **SHA-256 checksum** matches, each analysis checks **data drift** against
  the training data, and a **"What these numbers mean"** panel explains every result in plain language.
* Full details: [SECURITY.md](SECURITY.md) (how credentials are stored, every protection, deployment
  checklist) and [MODEL_CARD.md](MODEL_CARD.md) (what the model is for, how well it works, its limits).
* User guide: [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q --ignore=tests/smoke_test.py   # 69 security, account, admin, ML and API tests
python tests/smoke_test.py                                # end-to-end walkthrough of every feature
```

CI (`.github/workflows/ci.yml`) runs them on Linux, Windows and macOS for Python 3.11 to 3.13 on every push,
builds the dashboard, builds and starts the Docker image (health, headers, sign-up, non-root, read-only checks)
and scans dependencies for known vulnerabilities.

## Project layout

```
data/
  raw/            PaySim transaction data (real or synthetic)
  processed/      Access-event layer, labeled dataset, engineered features
src/
  generate_paysim.py                 Synthetic PaySim-style data generator (dev only)
  data_ingestion.py                  Week 1: load + profile + EDA figures
  access_event_generator.py          Week 2: vectorized + chunked, full-scale ready
  access_event_generator_v1_faker.py Week 1 version, kept for reference
  attack_injector.py                 Week 3: SIM-swap, PIN-sharing, agent-collusion labeling
  feature_engineering.py             Week 4: velocity, device/location, time-of-day features
  train_baseline_model.py            Week 5: XGBoost baseline + class-imbalance handling
  tune_and_compare_models.py         Week 6: hyperparameter search + MLP neural-net comparison
backend/
  main.py                            API routes only; wires the modules below together
  auth.py                            Accounts: register / sign in / sign out, profile, password, API keys
  schema.py                          Column vocabulary: recognises many spellings of each column
  features.py                        Raw data -> the model's 21 features (Week 4 logic for ANY dataset)
  scoring.py                         Loads the model; scores; per-transaction explanations (TreeSHAP)
  insights.py                        Automatic interpretation: findings, recommendations, thresholds
  overview.py                        Project-level summary + interpretation for the Overview page
  sources.py                         File / database / REST-API connectors
  sessions.py                        In-memory store of analysed datasets
  stream.py                          Real-time engine: per-account state, SSE broadcast, replay
  precompute_dashboard_data.py       Aggregates data into small dashboard/scoring files
  model.joblib                       Trained model (generated by src/train_baseline_model.py)
  data/                              Generated by the precompute script
  legacy/main_week7.py               The Week 7 API, kept for reference
frontend/                            React (Vite) dashboard; frontend/dist is the ready-built version
  src/pages/                         Sign-in/register, Overview, Analyze, Live, Check, Model, Account
  src/components/                    Charts, case drawer, tables, data-source panel, findings widgets
  legacy/week7-dashboard.html        The Week 7 single-file dashboard
tests/smoke_test.py                  End-to-end API test
docs/SUPERVISOR_BRIEFING.md          File-by-file briefing for the supervisor
notebooks/
  week2_access_event_layer_full_scale.ipynb
reports/
  figures/                 EDA plots
  baseline_metrics.json    Week 5 results
  model_comparison.json    Week 6 results
requirements.txt
start.sh / start.bat       One-command setup + start (macOS & Linux / Windows)
var/momo.db                User accounts (created on first run, not in git)
```

Large generated files are NOT included in this package (regenerate with the commands below):
`data/raw/paysim_real.csv` (471MB), `data/processed/access_events_full.csv` (1.4GB),
`data/processed/labeled_dataset.csv` (520MB), `data/processed/features.csv` (885MB).

## Setup (VS Code) — macOS

1. Install Python 3.12 (`brew install python@3.12`, or the "macOS 64-bit universal2" installer from
   [python.org/downloads/macos](https://www.python.org/downloads/macos/)), plus `brew install libomp` for XGBoost.
   Both Intel and Apple Silicon Macs are supported. (Or simply run `./start.sh`, see Quick start.)
2. Install [VS Code](https://code.visualstudio.com), then the **Python extension** from the Extensions panel (`Cmd+Shift+X`).
3. Clone the repo (`git clone https://github.com/OforiPrescott/momo-fraud-detection-week7.git`), then in VS Code: `File > Open Folder...` and select the cloned `momo-fraud-detection-week7` folder.
4. Open a terminal in VS Code (``Ctrl+` `` or `Terminal > New Terminal`). It should default to `zsh` or `bash`.
5. Create and activate a virtual environment, then install dependencies:
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
6. In VS Code's bottom-right corner, click the Python interpreter selector and choose the one inside `./venv`.
7. (Only needed to re-run the training pipeline, not to use the dashboard.) Download the real Kaggle PaySim1 CSV from kaggle.com/datasets/ealaxi/paysim1, rename it to
   `paysim_real.csv`, and place it in `data/raw/`.

## Setup (VS Code) — Windows

1. Install Python 3.11+ from [python.org/downloads](https://python.org/downloads). **Check "Add python.exe to PATH"**
   during install, this is unchecked by default and is the most common setup mistake.
2. Install [VS Code](https://code.visualstudio.com), then the **Python extension** from the Extensions panel (`Ctrl+Shift+X`).
3. Clone the repo (`git clone https://github.com/OforiPrescott/momo-fraud-detection-week7.git`), then in VS Code: `File > Open Folder...`
   and select the cloned `momo-fraud-detection-week7` folder.
4. Open a terminal in VS Code (``Ctrl+` `` or `Terminal > New Terminal`). It should default to PowerShell.
5. Create and activate a virtual environment, then install dependencies:

   ```powershell
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

   If PowerShell blocks the activation script with an execution-policy error, run this once first:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```
6. In VS Code's bottom-right corner, click the Python interpreter selector and choose the one inside `.\venv`.
7. (Only needed to re-run the training pipeline, not to use the dashboard.) Download the real Kaggle PaySim1 CSV from kaggle.com/datasets/ealaxi/paysim1, rename it to
   `paysim_real.csv`, and place it in `data\raw\`.

## Setup (VS Code) — Ubuntu

1. Install Python 3.11+:
   ```bash
   sudo apt update
   sudo apt install -y python3.11 python3.11-venv python3-pip
   ```
2. Install [VS Code](https://code.visualstudio.com), then the **Python extension** from the Extensions panel (`Ctrl+Shift+X`).
3. Clone the repo (`git clone https://github.com/OforiPrescott/momo-fraud-detection-week7.git`), then in VS Code: `File > Open Folder...` and select the cloned `momo-fraud-detection-week7` folder.
4. Open a terminal in VS Code (`Ctrl+`` ` or `Terminal > New Terminal`).
5. Create and activate a virtual environment, then install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
6. In VS Code's bottom-right corner, click the Python interpreter selector and choose the one inside `./venv`.
7. (Only needed to re-run the training pipeline, not to use the dashboard.) Download the real Kaggle PaySim1 CSV from kaggle.com/datasets/ealaxi/paysim1, rename it to
   `paysim_real.csv`, and place it in `data/raw/`.

## Setup (VS Code) — Fedora

1. Install Python 3.11+:
   ```bash
   sudo dnf install -y python3.11 python3.11-pip
   ```
2. Install [VS Code](https://code.visualstudio.com), then the **Python extension** from the Extensions panel (`Ctrl+Shift+X`).
3. Clone the repo (`git clone https://github.com/OforiPrescott/momo-fraud-detection-week7.git`), then in VS Code: `File > Open Folder...` and select the cloned `momo-fraud-detection-week7` folder.
4. Open a terminal in VS Code (`Ctrl+`` ` or `Terminal > New Terminal`).
5. Create and activate a virtual environment, then install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
6. In VS Code's bottom-right corner, click the Python interpreter selector and choose the one inside `./venv`.
7. (Only needed to re-run the training pipeline, not to use the dashboard.) Download the real Kaggle PaySim1 CSV from kaggle.com/datasets/ealaxi/paysim1, rename it to
   `paysim_real.csv`, and place it in `data/raw/`.

## Run the full pipeline, in order (same commands on all OSes, from the VS Code terminal)

```bash
# 1. Data ingestion + EDA  (~15s)
python src/data_ingestion.py --input data/raw/paysim_real.csv --figures

# 2. Synthetic access-event layer, full scale  (~70-150s)
python src/access_event_generator.py \
    --transactions data/raw/paysim_real.csv \
    --out data/processed/access_events_full.csv \
    --sim-swap-rate 0.03

# 3. Attack scenario labeling (SIM-swap, PIN-sharing, agent collusion)  (~165s)
python src/attack_injector.py \
    --transactions data/raw/paysim_real.csv \
    --access-events data/processed/access_events_full.csv \
    --out data/processed/labeled_dataset.csv

# 4. Feature engineering  (~270s)
python src/feature_engineering.py \
    --labeled data/processed/labeled_dataset.csv \
    --access-events data/processed/access_events_full.csv \
    --out data/processed/features.csv

# 5. Train the baseline model  (~165s)
python src/train_baseline_model.py --features data/processed/features.csv

# 6. Hyperparameter search + neural net comparison  (~4-5 min)
python src/tune_and_compare_models.py --features data/processed/features.csv

# 7. Precompute dashboard + scoring-sample data
python backend/precompute_dashboard_data.py

# 8. Start the API (from the project root). The built dashboard is served at the same address.
uvicorn backend.main:app --port 8000
#    -> open http://localhost:8000

# 9. (Optional) develop the dashboard with hot reload: needs Node 18+
cd frontend && npm install && npm run dev        # http://localhost:5173, talks to the API on :8000
#    npm run build   rebuilds frontend/dist for the single-server setup

# 10. Check everything works
python -m pytest tests -q --ignore=tests/smoke_test.py
python tests/smoke_test.py
```

## Week 8: bringing real data in, and real time

* **Analyse data** page: upload CSV / TSV / Excel / JSON / JSON Lines / Parquet (optionally .gz or .zip),
  connect a SQLite / PostgreSQL / MySQL database (read-only, single SELECT), or pull from a REST API.
  Column names are matched flexibly; missing inputs are reported, not hidden (signal coverage).
* **Automatic interpretation**: every analysis returns a headline, findings with evidence, and
  prioritised recommendations (do now / this week / plan for), recomputed instantly when the threshold moves.
* **Live monitor**: `POST /api/ingest` scores transactions one at a time as a platform sends them, keeping
  per-account history, and pushes each result to the dashboard over Server-Sent Events (`GET /api/stream`).
  A replay mode streams a dataset at 1-100 transactions per second for rehearsal.
* **Case drill-down**: any flagged transaction opens a "why" panel based on the model's own TreeSHAP values.

Environment variables:

| Variable | Default | What it does |
| --- | --- | --- |
| `MOMO_MAX_ROWS` | 1,000,000 | Largest dataset analysed |
| `MOMO_MAX_UPLOAD_MB` | 300 | Largest upload |
| `MOMO_DB_PATH` | `var/momo.db` | Where user accounts are stored |
| `MOMO_ALLOW_REGISTRATION` | 1 | Set to 0 to stop new sign-ups |
| `MOMO_SECURE_COOKIES` | 0 | Set to 1 once the site is served over HTTPS |
| `MOMO_ALLOW_PRIVATE_HOSTS` | 1 | Set to 0 on a shared server so the API/database connectors cannot reach internal addresses |
| `MOMO_ALLOW_SERVER_FILES` | 1 | Set to 0 on a shared server so visitors cannot read SQLite files on it |
| `MOMO_MAX_SESSIONS` | 24 | Analyses kept in memory across all users (3 per user) |
| `MOMO_CORS_ORIGINS` | none | Other websites allowed to call the API (same-origin only by default) |
| `MOMO_TRUSTED_ORIGINS` | none | Other origins allowed to send signed-in requests (e.g. a separately hosted frontend) |
| `MOMO_API_DOCS` | 1 | Set to 0 to hide the interactive API docs at `/docs` |
| `MOMO_MODEL_SHA256` | from `model.joblib.sha256` | Expected checksum of the model file |
| `MOMO_LOG_LEVEL` | INFO | Logging detail; security events are logged under `momo.security` |
| `MOMO_PUBLIC_URL` | none | Address users open the site at (e.g. `https://momo.example.org`); required for reset emails |
| `MOMO_SMTP_HOST` / `MOMO_SMTP_PORT` | none / 587 | Email server for password-reset links (587 STARTTLS or 465 TLS) |
| `MOMO_SMTP_USER` / `MOMO_SMTP_PASSWORD` / `MOMO_SMTP_FROM` | none | Email login and sender address |
| `MOMO_REQUIRE_2FA` | 0 | 1 = every account must turn on two-step sign-in before using the platform |
| `MOMO_ADMIN_EMAILS` | none | Comma-separated emails of administrators (they also need two-step sign-in) |
| `MOMO_SECRET_KEY` | none | Key that encrypts two-step secrets; without it a `secret.key` file is created next to the database |

`docker-compose.yml` already sets the shared-server values.

Note: steps 2-6 run on the full 6.36M-row real dataset and are memory-bounded for machines with
as little as 4GB RAM (several OOM crashes were hit and fixed during development, see the comments
at the top of each script for what each fix was and why). On a typical laptop with more RAM these
steps will run at least as fast, often faster.

## Results of the shipped model (same held-out test set, 98,304 transactions)

These are the figures in `reports/baseline_metrics.json` and `reports/model_comparison.json`, which describe
the model shipped in `backend/model.joblib`: 491,519 PaySim transactions, 393,215 for training and 98,304 held
out for testing, with 5.4% labelled as attacks.

| Model                     | Precision | Recall | F1    | AUC-ROC | AUC-PR |
| ------------------------- | --------- | ------ | ----- | ------- | ------ |
| XGBoost baseline (Week 5) | 0.999     | 1.000  | 0.999 | 1.000   | 1.000  |
| XGBoost tuned (Week 6)    | 0.999     | 1.000  | 0.999 | 1.000   | 1.000  |
| MLP neural net (Week 6)   | 0.999     | 0.984  | 0.991 | 0.999   | 0.998  |

On the test set the baseline flagged 5,305 transactions: all 5,300 labelled attacks (none missed) and 5 false
alarms.

**Key findings:**

- Target label is `any_attack_flag` (PaySim's `isFraud` OR any of the three Week 3 attack
  patterns), since this is an intrusion *and* fraud system, not a fraud-only one.
- All three models are close to perfect, and hyperparameter tuning did not beat the baseline: the simpler
  config (max_depth=4, 150 trees, learning rate 0.1) tied the more complex ones.
- **Read near-perfect scores with care.** The attack labels are produced by rules over the same device and SIM
  signals the model receives (for example, PIN-sharing is defined from device counts), so the model can
  reproduce them almost exactly. The scores show the labelling is learnable, not that real-world accuracy will
  be this high. Validating on real, independently labelled data is the next step, and the dashboard's upload,
  database and API options exist for that.
- `orig_distinct_devices` dominates feature importance (0.79), followed by the sender's balance before the
  transaction (0.10) and SIM change on record (0.04). Device and access signals do most of the work, which is
  the core argument for why intrusion-layer data matters for this problem.
- An earlier full-scale run on all 6.36M PaySim transactions scored lower precision (about 0.49) at similar
  recall; its model and result files are not part of this repository, so the dashboard and documents use the
  shipped model above.

## Week 8 — Dashboard (Nov 3-9)

Rich, production-ready SOC dashboard built as a React PWA served by the same FastAPI backend:

**Dashboard page**
- Richer filters: transaction-type dropdown, sender/receiver search, threshold slider, flag/replay controls
- Case drill-down: any flagged transaction opens a "why" panel based on the model's TreeSHAP values showing which features raised or lowered the risk score
- Side-by-side rule vs. model view: per-rule hit counts alongside model flagged counts, with overlap percentages
- Real data sources: upload CSV/TSV/Excel/JSON/Parquet (optionally gz/zip), connect SQLite/PostgreSQL/MySQL (read-only single SELECT), pull from a REST API, or stream live via `POST /api/ingest`
- Real-time scoring: live monitor keeps per-account state and pushes each scored transaction to the dashboard over Server-Sent Events (`GET /api/stream`), with replay at 1–100 transactions/second
- Automatic interpretation: every analysis returns a headline, key insights with evidence chips, and an in-dashboard interpretation that updates as the threshold moves
- Key insights span the full dashboard width so findings cover available space
- PWA: web app manifest + service worker for installability and offline resilience

## Week 9 — End-to-end integration testing (Nov 10-16)

* `tests/smoke_test.py` exercises the full stack end-to-end: API health → file upload → analysis → live ingest/stream → case drill-down → Model page results → Overview page summary
* Verifies model loads, scoring returns sensible precision/recall/AUC-PR on the held-out set, live stream reconnects on disconnect, replay produces analysis within 20 transactions
* Confirms all dashboard pages render without server errors and recommendations/findings are grounded in evidence chips traced to computed counts
* Run: `python tests/smoke_test.py` (with the API running on port 8000)

## Week 10 — Deployment packaging (Nov 17-23)

Single-container deployment packaging backend + frontend together:

* `Dockerfile` at the project root builds the Python backend, installs frontend Node dependencies, runs `npm run build` into `frontend/dist`, then starts the API which serves the built dashboard at `/`
* `docker-compose.yml` orchestrates the single container (extendable to separate web and worker services)
* Build: `docker-compose up --build` → dashboard at `http://localhost:8000`
* The backend serves `frontend/dist` directly, so no separate frontend hosting is needed
* Environment variables (see the table above) are passed at runtime for production hardening; user accounts are kept in the mounted `./var` folder

## Week 11 — Polish, documentation, buffer (Nov 24-30)

* Currency selector supports GHS, USD, NGN, KES, GBP, EUR, ZAR, UGX, TZS, XOF, XAF, GMD, SLL, LRD, MWK, ZMW, BWP, NAD, MAD, EGP, KWD, AED, SAR, JPY, INR, CNY, CAD, AUD — any country's organization can analyse their data
* Mobile-responsive layout (horizontal sidebar below 900px, single-column grids below 600px)
* Removed internal/supervisor-specific language ("agree with supervisor", "MSc thesis", "needs to agree") so the dashboard is standalone for organizational use
* Key insights cards span full width; findings and recommendations separated into review-ready content
* README documentation updated to cover all 11 weeks of the roadmap
* Buffer used for final smoke-test pass and PWA verification before release

## Roadmap (Sept 15 - Nov 30)

| Week | Dates        | Build focus                                                                                                                                        | Status              |
| ---- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| 1    | Sep 15-21    | Data ingestion, EDA, synthetic access-event layer                                                                                                  | Done                |
| 2    | Sep 22-28    | Finalize access-event layer at full scale (vectorized + chunked)                                                                                   | Done                |
| 3    | Sep 29-Oct 5 | Ghana-specific attack scenario injection + interface skeleton (FastAPI + JS dashboard)                                                             | Done                |
| 4    | Oct 6-12     | Feature engineering (velocity, device/location change, time-of-day anomalies)                                                                      | Done                |
| 5    | Oct 13-19    | Baseline XGBoost model, class imbalance handling                                                                                                   | Done                |
| 6    | Oct 20-26    | Model tuning, evaluation, neural net comparison                                                                                                    | Done                |
| 7    | Oct 27-Nov 2 | Wire trained model into the API (live scoring, replacing precomputed labels)                                                                       | Done                |
| 8    | Nov 3-9      | Dashboard: richer filters, case drill-down, side-by-side rule vs. model view (plus real data sources, real-time scoring, automatic interpretation) | Done                |
| 9    | Nov 10-16    | End-to-end integration testing                                                                                                                     | Done                |
| 10   | Nov 17-23    | Deployment packaging (Docker, backend + frontend together)                                                                                         | Done                |
| 11   | Nov 24-30    | Polish, documentation, buffer                                                                                                                      | Done                |

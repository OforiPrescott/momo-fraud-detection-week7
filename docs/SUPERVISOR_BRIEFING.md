# Week 8 Briefing: From a Static Dashboard to a Real-Time Detection Platform

Frank Johnfia, MSc Cybersecurity, Grand Valley State University. Prepared 15 October 2026.
Project: Machine Learning-Based Intrusion and Fraud Detection System for Mobile Money Platforms in Ghana.

## 1. The short version

In Weeks 1 to 7 I built the data pipeline, the labels, the features and two compared models, and wired the trained model into a small API and dashboard. That dashboard could only show results from one fixed sample.

This update turns it into something that works on any data and works in real time:

- **Bring your own data.** Upload a file (CSV, TSV, Excel, JSON, JSON Lines, Parquet, optionally compressed), connect a database (SQLite, PostgreSQL, MySQL, read-only), or pull from a REST API. The same features used in training are rebuilt from whatever arrives.
- **Automatic interpretation.** After every analysis the dashboard writes a headline, a list of findings with the numbers behind them, and prioritised recommendations. Nothing needs to be read off a chart by hand.
- **Real time.** A platform can send each transaction to an ingest endpoint; it is scored in a few milliseconds and appears on the dashboard immediately, with the reasons. A replay mode lets me demonstrate this without a live feed.
- **Explanations.** Every flagged transaction opens a panel showing which inputs pushed its score up or down.
- **Rebuilt in React**, branded with the university logo.

## 2. What changed from Week 7

| Area | Week 7 | Now |
|---|---|---|
| Data | One precomputed 5,000-row sample | Any file, database table or API feed |
| Interpretation | Reader looks at charts | Written automatically, with evidence and actions |
| Real time | Re-run to refresh | Transactions scored as they arrive and streamed to the screen |
| Threshold | Fixed at 0.5 | Slider; everything recomputes instantly; suggested settings |
| Case detail | Table row only | Drill-down with per-transaction reasons |
| Rules vs model | Toggle between two views | Side-by-side comparison, plus model-only alerts |
| Frontend | One HTML file, Chart.js | React app, five pages |

## 3. How it works, in five steps

1. **Ingest.** A file, database query, API response or single live transaction arrives.
2. **Map.** Column names are recognised in many spellings (for example `amt`, `value` or `amount`; `sender_id` or `nameOrig`). Transaction types such as "withdrawal" are mapped to CASH_OUT.
3. **Build features.** The 21 model inputs are rebuilt exactly as in Week 4. For each one the system records whether it was *provided*, *derived* or had to be *defaulted*.
4. **Score and explain.** The trained XGBoost model gives each transaction a risk score between 0 and 1. TreeSHAP values give the reason for each score.
5. **Interpret.** A deterministic rule engine turns the scored data into findings and recommendations. Every sentence is built from counts computed on the data, so each claim can be traced back to evidence.

## 4. What powers each dashboard page

| Page | What the analyst sees | API endpoints used | Backend modules | Data or model underneath |
|---|---|---|---|---|
| Overview | Project headline, KPIs, charts, findings, next steps | `/api/overview` | `overview.py`, `scoring.py` | `dashboard_summary.json`, `reports/*.json`, `model.joblib` |
| Analyse data | Source picker, threshold slider, briefing, risk ribbon, findings, actions, charts, cases, data quality | `/api/analyze/upload`, `/database`, `/api`, `/sample`; `/api/analysis/{id}` and its `/flagged`, `/case/{row}`, `/export.csv` | `main.py`, `sources.py`, `features.py`, `scoring.py`, `insights.py`, `sessions.py` | Whatever the user supplies; `model.joblib` |
| Live monitor | Feed, pulse strip, counters, live briefing | `/api/stream` (events), `/api/ingest`, `/api/stream/replay`, `/api/stream/config` | `stream.py`, `scoring.py`, `insights.py` | In-memory per-account history; `scoring_sample.csv` for replay |
| Check a transaction | Type in one transaction, see score and reasons | `/api/score` | `main.py`, `scoring.py` | `model.joblib` |
| Model results | Model comparison, importance, workload, trade-off notes | `/api/overview` | `overview.py` | `baseline_metrics.json`, `model_comparison.json`, `model.joblib` |

## 5. Every code file and its role

### 5.1 `src/` (Weeks 1 to 6, the pipeline that creates the data and the model)

These files are unchanged. They run offline and produce the files the dashboard consumes.

| File | Role | Where it shows up on the dashboard |
|---|---|---|
| `generate_paysim.py` | Developer-only synthetic PaySim generator for quick runs | Not shown |
| `data_ingestion.py` | Week 1: loads, profiles and plots the raw data | Source of the Week 1 figures quoted in the findings |
| `access_event_generator_v1_faker.py` | Week 1 device and SIM generator, kept for reference | Not shown |
| `access_event_generator.py` | Week 2: builds the device, login and SIM-change layer at full scale | Creates the device signal that is the model's strongest predictor |
| `attack_injector.py` | Week 3: labels SIM-swap takeover, PIN-sharing abuse and agent collusion | Overview KPIs; the "rules versus model" comparison |
| `feature_engineering.py` | Week 4: velocity, device and time-of-day features | Defines the 21 inputs; `backend/features.py` repeats this logic for new data |
| `train_baseline_model.py` | Week 5: trains the XGBoost baseline | Produces `model.joblib` and `baseline_metrics.json`; powers every score |
| `tune_and_compare_models.py` | Week 6: tuning and neural-net comparison | Produces `model_comparison.json`; Model results page |
| `paysim_param_files/` | Calibration inputs for the simulator | Not shown |

### 5.2 `backend/` (the Python API; this is where the new engineering is)

| File | Role | What it powers |
|---|---|---|
| `main.py` | Defines all HTTP routes and nothing else; hands the work to the modules below. Keeps the old Week 7 endpoints working | Every page |
| `schema.py` | Dictionary of accepted column names and transaction-type synonyms | Lets real exports load without renaming columns |
| `features.py` | Rebuilds the 21 model inputs from raw data; tracks provided, derived or defaulted; re-derives rule labels when device data is present | "Data quality" tab; signal-coverage warning |
| `scoring.py` | Loads `model.joblib` once; scores; computes TreeSHAP reasons; turns reasons into plain English | Risk scores everywhere; "Why" panels |
| `insights.py` | The interpretation engine: headline, findings, recommendations, response tiers, threshold suggestions, accuracy when labels exist | Briefing, findings, actions, ribbon, threshold buttons |
| `overview.py` | Same style of interpretation for the whole project (6.36M rows and the model comparison) | Overview and Model pages |
| `sources.py` | Readers for files, databases and REST APIs, with safety checks (read-only SQL, blocked internal addresses, size and row caps) | The four data-source tabs |
| `sessions.py` | Keeps the last six analysed datasets in memory | Threshold slider, drill-down and export without re-uploading |
| `stream.py` | Real-time engine: per-account history, one-at-a-time scoring, broadcast to every open dashboard, replay | Live monitor |
| `precompute_dashboard_data.py` | Week 7 script that shrinks the big dataset into small files | Creates the Overview numbers and the sample |
| `model.joblib` | The trained XGBoost model and its feature order | All scoring |
| `data/dashboard_summary.json`, `flagged_samples.csv`, `scoring_sample.csv` | Small precomputed summaries and a 5,000-row labelled sample | Overview, project sample, replay |
| `legacy/main_week7.py` | The Week 7 API, kept so the old version can be compared | Not used |

### 5.3 `frontend/` (the React dashboard)

| File | Role |
|---|---|
| `index.html`, `package.json`, `vite.config.js` | Project shell, dependencies and build settings |
| `public/gvsu-logo-white.svg` | The university logo shown in the navigation rail |
| `src/main.jsx` | Starts the app and wraps it in the settings and live-stream providers |
| `src/App.jsx` | Page layout, navigation, API health indicator, currency selector; keeps the current analysis when switching pages |
| `src/api.js` | The only place that talks to the backend (base address and error handling) |
| `src/format.js` | Number, money and colour helpers so every page formats values the same way |
| `src/settings.jsx` | Remembers the currency label across reloads |
| `src/live.jsx` | Holds the live connection above the pages so the feed keeps running when the user changes tab; batches fast events into smooth screen updates |
| `src/styles.css` | The design system: colours from the university logo, risk colour scale, typography, responsive layout, print styles |
| `src/components/ui.jsx` | Shared pieces: KPI strip, briefing panel, **risk ribbon**, findings list, recommendations, "why" bars, icons |
| `src/components/Charts.jsx` | All charts: by type, by hour, score distribution, threshold trade-off, model comparison |
| `src/components/SourcePanel.jsx` | The four ways to bring data in |
| `src/components/FlaggedTable.jsx` | Filter, search, sort, page and export the flagged transactions |
| `src/components/CaseDrawer.jsx` | Drill-down panel: details, reasons, related alerts, input provenance |
| `src/components/DataQuality.jsx` | How much of the model's signal the data supplied |
| `src/pages/Overview.jsx`, `Analyze.jsx`, `Live.jsx`, `Check.jsx`, `Model.jsx` | The five pages |
| `legacy/week7-dashboard.html` | The Week 7 dashboard, kept for comparison |
| `dist/` | The built dashboard, served directly by the API so one command runs everything |

### 5.4 Other

| File | Role |
|---|---|
| `requirements.txt` | Python dependencies, extended for uploads and databases |
| `README.md` | Setup, run commands and structure (updated) |
| `tests/smoke_test.py` | End-to-end test of the API |
| `reports/` | Week 5 and 6 metrics and the EDA figures |

## 6. How the automatic interpretation works

The engine looks for specific patterns and only reports one when the data supports it. Each finding carries its evidence, and each recommendation is linked to the finding that triggered it.

| Pattern checked | Example finding | Example recommendation |
|---|---|---|
| Overall flagged share and critical alerts | "13.8% of transactions were flagged" | Work the critical alerts first |
| Concentration by transaction type | "TRANSFER carries the highest alert rate" | Stricter limits on that channel |
| Late-night activity | "Overnight transactions are riskier" | Tighter limits from 00:00 to 05:00 |
| Multi-device accounts | "39% of alerts come from accounts on two or more devices" | Step-up verification on a new device |
| SIM change followed by a large cash-out | "High-value cash-outs follow SIM changes" | Cooling-off period after a SIM change |
| Accounts emptied in one move | "180 flagged transactions leave the wallet at zero" | Hold full-balance withdrawals |
| Repeat senders and receiver hubs | "Flagged payments are converging on a few receivers" | Investigate those accounts |
| Amounts just under the 200,000 limit | "Amounts cluster just under the flagging limit" | Add a structuring rule |
| Accuracy, when labels exist | "99.7% recall, 53.5% precision" | A better threshold, with the figures |
| Missing data | "Only 17% of the model's signal was available" | Collect device and SIM data |

Every analysis also splits transactions into four response tiers (hold, verify, watch, allow), shown as the ribbon on the Analyse and Live pages.

## 7. Results from the built-in sample

On the 5,000-row labelled sample, analysed in under a tenth of a second:

| Threshold | Flagged | Precision | Recall |
|---|---|---|---|
| 0.50 (default) | 690 (13.8%) | 53.5% | 99.7% |
| 0.88 (best balance) | 329 (6.6%) | 93.9% | 83.5% |
| 0.64 (catch 95%) | 539 (10.8%) | 65.3% | 95.1% |

This reproduces, on a small scale, the trade-off found in Week 6: at the default setting the model catches nearly everything but about half of its alerts are false. The dashboard now lets that choice be made deliberately.

The same sample, stripped down to raw PaySim columns with no device information, reaches only **17.2% signal coverage** and the average risk score drops from 0.117 to 0.001. The dashboard warns about this instead of silently reporting "low risk".

## 8. Real time: what is and is not demonstrated

- A transaction sent to `POST /api/ingest` is scored and appears on every open dashboard within about a second, with the reasons for any alert. I verified this over HTTP against the running server.
- Per-account history (previous transactions, devices seen, SIM change, how many senders paid a receiver) is kept in memory, so the features behave as they did in training.
- In testing, a replay at 80 transactions per second was sustained. Scoring costs roughly 1 millisecond per transaction in a batch, and about 10 milliseconds when a single transaction is also explained.
- The live panel re-runs the interpretation every few seconds over the latest 800 transactions.
- **Not yet demonstrated:** a real production feed. The ingest endpoint is ready for one; the replay is a rehearsal.

## 9. Limitations I want to be upfront about

1. **The labels are rule-derived and synthetic.** The attack labels come from my own rules on a synthetic device layer, and the PIN-sharing rule is defined from device counts. So the finding that device behaviour is the top predictor partly reflects how the labels were built. Testing on independently labelled real data is the stronger evidence, and that is what the new data sources are for. The dashboard says this on the Model page.
2. **Device data is essential.** Without it the model has far less to work with, as section 7 shows.
3. **Only the XGBoost model is served.** The neural net is compared in the results but is not deployed behind the API.
4. **Recommendations are suggestions, not validated controls.** They come from common fraud-prevention practice and the patterns in the data. The numbers attached to them are measured; the effectiveness of the controls is not.
5. **Interpretation is rule-based by design.** It is traceable and repeatable, but it only reports the patterns it was written to look for.
6. **Single-user prototype.** Analyses are kept in memory, there is no login, and live settings are shared by everyone connected.
7. **Not ready for real customer data as it stands.** Before deployment: restrict allowed origins, require the ingest key, add authentication and HTTPS, and disable private-address access in the API connector. Using real customer data also needs approval under the university's research-ethics process and the requirements of Ghana's Data Protection Act, which I would like guidance on.
8. **Row limit.** Files above one million rows are sampled (configurable).

## 10. Decisions and questions for my supervisor

1. Which error costs more in a live mobile money system, a missed attack or a false alarm? The answer sets the threshold and decides which model ships.
2. Can we obtain a real, investigator-labelled sample (even a small one) with device or SIM information, to test the model outside the synthetic labels?
3. Should the thesis present a tiered response (hold, verify, watch, allow) using both models, and should I test that combination in Week 9?
4. What deployment target should Week 10 packaging assume: a university server, a cloud host, or a demonstration on my laptop?
5. What ethical-approval steps apply if a partner shares real transaction data?

## 11. A five-minute demonstration

1. **Overview.** Read the headline and the "financial fraud sees only a sliver of the risk" finding.
2. **Analyse data, Project sample.** Show the briefing, the risk ribbon, the findings and the actions. Move the threshold slider and press "Best balance".
3. **Cases.** Open the top transaction and read the "why" panel.
4. **Analyse data, upload.** Drop a CSV without device columns and show the signal-coverage warning.
5. **Live monitor.** Start the replay at 20 per second, open a flagged transaction, and show the live briefing updating. Then run the `curl` command from "Connect your own system" and watch the transaction appear.
6. **Model results.** Close on the precision and recall trade-off and the questions in section 10.

## 12. How this maps to the roadmap

| Week | Planned | Status |
|---|---|---|
| 8 | Richer filters, case drill-down, rule-versus-model view | Built, plus real data sources, real-time scoring and automatic interpretation |
| 9 | End-to-end integration testing | Smoke test written; needs testing on real data and with a second user |
| 10 | Deployment packaging (Docker) | Not started; one server already serves both API and dashboard, which simplifies it |
| 11 | Polish, documentation, buffer | README and this briefing updated |

## 13. How to run it

From the project folder, after `pip install -r requirements.txt`:

```
uvicorn backend.main:app --port 8000
```

Open `http://localhost:8000`. To edit the dashboard, run `npm install` then `npm run dev` inside `frontend/`, and open `http://localhost:5173`.

"""
Presentation layer (SOC analyst dashboard) API.

Serves the small precomputed files from precompute_dashboard_data.py for
the rule-based views (Week 1-3 work), AND (Week 7) loads the trained
model from Week 5/6 to score transactions live, rather than only serving
precomputed rule-based flags.

Deliberately does NOT load the 6.36M-row labeled dataset or the ~900MB
features.csv on every request, or even at startup: only the small
precomputed JSON/CSV summaries and the small scoring_sample.csv, so the
API stays fast and lightweight regardless of how large the underlying
dataset grows. The model itself (a few hundred KB) is loaded once at
startup.

Run (from the project root):
    uvicorn backend.main:app --reload --port 8000
Then open frontend/index.html in a browser (it calls this API at
http://localhost:8000).
"""
import json
import os

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MODEL_PATH = os.path.join(HERE, "model.joblib")

app = FastAPI(title="MoMo Fraud & Intrusion Detection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only: a real deployment would restrict this to the dashboard's origin
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_model_bundle = None  # loaded lazily on first use, see get_model_bundle()


def get_model_bundle():
    global _model_bundle
    if _model_bundle is None:
        if not os.path.exists(MODEL_PATH):
            raise HTTPException(
                status_code=404,
                detail="Model not found. Run src/train_baseline_model.py or "
                       "src/tune_and_compare_models.py first.",
            )
        _model_bundle = joblib.load(MODEL_PATH)
    return _model_bundle


class ScoreRequest(BaseModel):
    amount: float
    amount_log: float
    oldbalanceOrg: float
    newbalanceOrig: float
    oldbalanceDest: float
    newbalanceDest: float
    balance_error_orig: float
    balance_error_dest: float
    hour_of_day: int
    is_night: int
    orig_txn_count_so_far: int
    orig_avg_amount_so_far: float
    amount_to_avg_ratio: float
    orig_distinct_devices: int
    orig_ever_sim_change: int
    dest_distinct_senders: int
    type: str  # one of CASH_IN, CASH_OUT, DEBIT, PAYMENT, TRANSFER


@app.get("/api/summary")
def get_summary():
    path = os.path.join(DATA_DIR, "dashboard_summary.json")
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="Summary not found. Run backend/precompute_dashboard_data.py first.",
        )
    with open(path) as f:
        return json.load(f)


@app.get("/api/flagged")
def get_flagged(pattern: str = "sim_swap_takeover", limit: int = 50):
    valid_patterns = {"sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag"}
    if pattern not in valid_patterns:
        raise HTTPException(status_code=400, detail=f"pattern must be one of {valid_patterns}")

    path = os.path.join(DATA_DIR, "flagged_samples.csv")
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="Samples not found. Run backend/precompute_dashboard_data.py first.",
        )
    df = pd.read_csv(path)
    subset = df[df["matched_pattern"] == pattern].head(limit)
    return subset.to_dict(orient="records")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/score")
def score_transaction(req: ScoreRequest):
    """Week 7: live model scoring. Takes a feature vector for ONE
    transaction and returns the trained model's fraud/intrusion
    probability, rather than a precomputed rule-based flag."""
    bundle = get_model_bundle()
    model, feature_cols = bundle["model"], bundle["feature_columns"]

    row = req.dict()
    txn_type = row.pop("type")
    for t in ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]:
        row[f"type_{t}"] = 1 if txn_type == t else 0

    X = pd.DataFrame([row])[feature_cols]  # enforce exact column order used at training time
    proba = float(model.predict_proba(X)[0, 1])
    return {
        "risk_score": round(proba, 4),
        "predicted_label": int(proba >= 0.5),
        "model_features_used": feature_cols,
    }


@app.get("/api/model-flagged")
def model_flagged(limit: int = 25):
    """Week 7: scores a sample of real transactions LIVE through the
    trained model and returns the highest-risk ones, replacing the
    precomputed rule-based /api/flagged view with actual model output."""
    bundle = get_model_bundle()
    model, feature_cols = bundle["model"], bundle["feature_columns"]

    path = os.path.join(DATA_DIR, "scoring_sample.csv")
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail="scoring_sample.csv not found. Run backend/precompute_dashboard_data.py first.",
        )
    df = pd.read_csv(path)
    type_dummies = pd.get_dummies(df["type"], prefix="type", dtype=int)
    for t in ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]:
        if f"type_{t}" not in type_dummies.columns:
            type_dummies[f"type_{t}"] = 0
    X = pd.concat([df, type_dummies], axis=1)[feature_cols]

    df["risk_score"] = model.predict_proba(X)[:, 1]
    top = df.sort_values("risk_score", ascending=False).head(limit)
    cols = ["step", "type", "amount", "nameOrig", "nameDest", "risk_score", "any_attack_flag"]
    return top[cols].to_dict(orient="records")

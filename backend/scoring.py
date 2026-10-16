"""
Model loading, scoring and explanation.

Explanations use XGBoost's built-in TreeSHAP (``pred_contribs=True``): for
every transaction, each feature gets a signed contribution to the final
risk score. That is what turns "risk 0.97" into "because the sender used 3
devices and the amount was 6x their usual amount".
"""
import os
import threading
import warnings

import joblib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.environ.get("MOMO_MODEL_PATH", os.path.join(HERE, "model.joblib"))

_lock = threading.Lock()
_bundle = None


class ModelMissing(RuntimeError):
    pass


def bundle():
    global _bundle
    with _lock:
        if _bundle is None:
            if not os.path.exists(MODEL_PATH):
                raise ModelMissing(
                    "Model not found. Run src/train_baseline_model.py or src/tune_and_compare_models.py first."
                )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _bundle = joblib.load(MODEL_PATH)
        return _bundle


def feature_columns():
    return list(bundle()["feature_columns"])


def importances() -> dict:
    b = bundle()
    imp = np.asarray(b["model"].feature_importances_, dtype=float)
    total = imp.sum() or 1.0
    return {c: float(v / total) for c, v in zip(b["feature_columns"], imp)}


def score(X: pd.DataFrame) -> np.ndarray:
    b = bundle()
    return b["model"].predict_proba(X[b["feature_columns"]].astype("float32"))[:, 1]


def contribs(X: pd.DataFrame):
    """Signed per-feature contributions (log-odds). Returns (matrix, bias) or None."""
    try:
        import xgboost as xgb

        b = bundle()
        cols = b["feature_columns"]
        dm = xgb.DMatrix(X[cols].astype("float32"), feature_names=cols)
        raw = b["model"].get_booster().predict(dm, pred_contribs=True)
        return raw[:, :-1], raw[:, -1]
    except Exception:  # explanations are a bonus; scoring must never fail because of them
        return None


# --- plain-language descriptions ------------------------------------------------

LABELS = {
    "amount": "Transaction amount",
    "amount_log": "Transaction amount (log scale)",
    "oldbalanceOrg": "Sender balance before",
    "newbalanceOrig": "Sender balance after",
    "oldbalanceDest": "Receiver balance before",
    "newbalanceDest": "Receiver balance after",
    "balance_error_orig": "Sender ledger mismatch",
    "balance_error_dest": "Receiver ledger mismatch",
    "hour_of_day": "Hour of day",
    "is_night": "Late-night activity",
    "orig_txn_count_so_far": "Sender history length",
    "orig_avg_amount_so_far": "Sender typical amount",
    "amount_to_avg_ratio": "Amount vs sender's usual",
    "orig_distinct_devices": "Devices used by sender",
    "orig_ever_sim_change": "SIM change on record",
    "dest_distinct_senders": "Receiver fan-in",
    "type_CASH_IN": "Transaction type: cash-in",
    "type_CASH_OUT": "Transaction type: cash-out",
    "type_DEBIT": "Transaction type: debit",
    "type_PAYMENT": "Transaction type: payment",
    "type_TRANSFER": "Transaction type: transfer",
}


def _n(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def describe(feature: str, value) -> str:
    """One short phrase describing what the value is, for the 'why' list."""
    v = float(value)
    if feature == "orig_distinct_devices":
        return f"Sender account seen on {int(v)} device{'s' if int(v) != 1 else ''}"
    if feature == "orig_ever_sim_change":
        return "A SIM change is on record for the sender" if v >= 1 else "No SIM change on record"
    if feature == "dest_distinct_senders":
        return f"Receiver has been paid by {int(v)} different sender{'s' if int(v) != 1 else ''}"
    if feature == "amount_to_avg_ratio":
        return f"Amount is {v:.1f}x the sender's usual amount"
    if feature in ("amount", "amount_log"):
        return f"Amount of {_n(np.expm1(v) if feature == 'amount_log' else v)}"
    if feature == "is_night":
        return "Happened between 00:00 and 05:00" if v >= 1 else "Happened outside the late-night window"
    if feature == "hour_of_day":
        return f"Happened at {int(v):02d}:00"
    if feature == "newbalanceOrig":
        return "Sender balance left at zero" if v == 0 else f"Sender balance after: {_n(v)}"
    if feature == "oldbalanceOrg":
        return f"Sender balance before: {_n(v)}"
    if feature in ("balance_error_orig", "balance_error_dest"):
        return "Ledger balances do not add up" if abs(v) > 0.01 else "Ledger balances add up"
    if feature == "orig_txn_count_so_far":
        return f"Sender had {int(v)} earlier transaction{'s' if int(v) != 1 else ''} in the data"
    if feature.startswith("type_"):
        return LABELS[feature]
    return f"{LABELS.get(feature, feature)}: {_n(v)}"


def explain_rows(X: pd.DataFrame, top: int = 5):
    """List (one per row) of the strongest drivers: feature, label, text, impact, direction."""
    res = contribs(X)
    if res is None:
        return [[] for _ in range(len(X))]
    mat, _ = res
    cols = feature_columns()
    out = []
    for i in range(len(X)):
        order = np.argsort(-np.abs(mat[i]))[: top + 3]
        items = []
        for j in order:
            if abs(mat[i, j]) < 0.02:
                continue
            f = cols[j]
            if f.startswith("type_") and float(X.iloc[i][f]) < 1 and abs(mat[i, j]) < 0.3:
                continue  # "is not a PAYMENT" is noise
            items.append({
                "feature": f,
                "label": LABELS.get(f, f),
                "text": describe(f, X.iloc[i][f]),
                "impact": round(float(mat[i, j]), 3),
                "direction": "up" if mat[i, j] > 0 else "down",
            })
            if len(items) == top:
                break
        out.append(items)
    return out

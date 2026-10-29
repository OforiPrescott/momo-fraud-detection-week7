"""
Data drift: how different is the data being scored from the data the model learned from?

A model is only as trustworthy as the match between its training data and what it now sees. For each
model input that the user's data actually supplied, the Population Stability Index (PSI) compares its
distribution with the project's reference sample (backend/data/scoring_sample.csv, drawn from the
training feature set):

    PSI = sum over bins of (actual% - expected%) * ln(actual% / expected%)

Industry rule of thumb (credit-risk model monitoring): below 0.10 stable, 0.10-0.25 moderate shift,
above 0.25 major shift. Inputs that fell back to a default value are skipped (they are already reported
as missing). The result is shown on the Data quality tab and, when shifts are large, as a finding.
"""
import os
import threading

import numpy as np
import pandas as pd

from . import scoring

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(HERE, "data", "scoring_sample.csv")
BINS, EPS = 10, 1e-4
STABLE, MODERATE = 0.10, 0.25
_ref = None
_lock = threading.Lock()


def _reference():
    global _ref
    with _lock:
        if _ref is None:
            df = pd.read_csv(REFERENCE)
            cols = [c for c in scoring.feature_columns() if c in df]
            _ref = df[cols].astype("float64").replace([np.inf, -np.inf], np.nan)
        return _ref


def psi(expected: np.ndarray, actual: np.ndarray) -> float:
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) == 0 or len(actual) == 0:
        return 0.0
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, BINS + 1)))
    if len(edges) < 2:  # the reference is constant: compare "same value" vs "different"
        same_e = 1.0
        same_a = float(np.mean(np.isclose(actual, edges[0])))
        e, a = np.array([same_e, 1 - same_e]), np.array([same_a, 1 - same_a])
    else:
        edges[0], edges[-1] = -np.inf, np.inf
        e = np.histogram(expected, edges)[0] / len(expected)
        a = np.histogram(actual, edges)[0] / len(actual)
    e, a = np.clip(e, EPS, None), np.clip(a, EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def level(value: float) -> str:
    return "stable" if value < STABLE else "moderate" if value < MODERATE else "major"


def compute(X: pd.DataFrame, feature_sources: dict) -> dict:
    """Per-input PSI against the training reference, for inputs the data supplied (provided or derived)."""
    try:
        ref = _reference()
    except (OSError, ValueError):
        return {"available": False, "features": []}
    rows = []
    for col in X.columns:
        if feature_sources.get(col, "default") == "default" or col not in ref:
            continue
        v = psi(ref[col].to_numpy(), X[col].to_numpy(dtype="float64"))
        rows.append({"feature": col, "label": scoring.LABELS.get(col, col), "psi": round(v, 3), "level": level(v),
                     "reference_median": float(np.nanmedian(ref[col])), "your_median": float(np.nanmedian(X[col]))})
    rows.sort(key=lambda r: -r["psi"])
    majors = [r for r in rows if r["level"] == "major"]
    moderates = [r for r in rows if r["level"] == "moderate"]
    overall = "major" if majors else "moderate" if moderates else "stable"
    if not rows:
        summary = "No model inputs were supplied directly, so similarity to the training data could not be checked."
    elif overall == "stable":
        summary = (f"All {len(rows)} inputs your data supplied look like the data the model was trained on, "
                   "so its scores should behave as tested.")
    elif overall == "moderate":
        summary = (f"{len(moderates)} of {len(rows)} inputs differ somewhat from the training data. Scores are "
                   "usable, but check flagged cases before acting on them.")
    else:
        summary = (f"{len(majors)} of {len(rows)} inputs differ strongly from the training data "
                   f"({', '.join(r['label'].lower() for r in majors[:3])}). Treat scores as indicative until the "
                   "model is validated or retrained on data like yours.")
    return {"available": bool(rows), "overall": overall, "summary": summary, "features": rows,
            "thresholds": {"stable": STABLE, "moderate": MODERATE}}


def insight(d: dict):
    """A finding for the Findings tab when the data has shifted enough to matter, else None."""
    if not d.get("available") or d["overall"] == "stable":
        return None
    shifted = [r for r in d["features"] if r["level"] != "stable"]
    return {
        "id": "drift", "severity": "high" if d["overall"] == "major" else "medium",
        "title": "Your data differs from the data the model learned from",
        "finding": d["summary"] + " This is called data drift: the further new data is from the training data, "
                                  "the less the measured accuracy can be relied on.",
        "evidence": [{"label": r["label"], "value": f"PSI {r['psi']:.2f} ({r['level']})"} for r in shifted[:4]],
    }

"""Model and data tests: scoring sanity, drift detection, input cleaning, explanations, interpretation."""
import numpy as np
import pandas as pd

from backend import drift, features, scoring


def _sample():
    return pd.read_csv("backend/data/scoring_sample.csv")


def test_model_scores_are_probabilities():
    X, _, _ = features.prepare(_sample().head(500))
    risk = scoring.score(X)
    assert risk.shape == (500,) and np.all((risk >= 0) & (risk <= 1))


def test_model_separates_attacks_on_labelled_sample():
    df = _sample()
    X, frame, _ = features.prepare(df)
    risk = scoring.score(X)
    y = frame["label"].to_numpy()
    assert risk[y == 1].mean() > 0.8 and risk[y == 0].mean() < 0.2


def test_scores_are_deterministic():
    X, _, _ = features.prepare(_sample().head(200))
    assert np.array_equal(scoring.score(X), scoring.score(X))


def test_psi_is_zero_for_same_distribution_and_large_for_shift():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 5000)
    assert drift.psi(a, rng.normal(0, 1, 5000)) < drift.STABLE
    assert drift.psi(a, rng.normal(3, 1, 5000)) > drift.MODERATE


def test_drift_flags_data_unlike_training():
    df = _sample().head(1000).copy()
    df["amount"] = df["amount"] * 1000  # amounts a thousand times larger than anything trained on
    X, _, meta = features.prepare(df)
    d = drift.compute(X, meta["feature_sources"])
    assert d["overall"] == "major" and drift.insight(d)["severity"] == "high"


def test_project_sample_is_not_drifted():
    X, _, meta = features.prepare(_sample())
    assert drift.compute(X, meta["feature_sources"])["overall"] == "stable"


def test_bad_inputs_are_cleaned_and_reported():
    df = pd.DataFrame({"type": ["PAYMENT", "CASH_OUT", "TRANSFER", "PAYMENT"],
                       "amount": [100, -250, "inf", "abc"], "oldbalanceOrg": [1e400, 300, 10, 5]})
    X, frame, meta = features.prepare(df)
    assert np.isfinite(X.to_numpy()).all()
    text = " ".join(meta["warnings"])
    assert "negative amount" in text and "non-numeric amount" in text
    assert (frame["amount"] >= 0).all()


def test_missing_required_columns_explained():
    try:
        features.prepare(pd.DataFrame({"a": [1]}))
        assert False, "should have failed"
    except ValueError as e:
        assert "amount" in str(e) and "type" in str(e)


def test_explanations_name_the_drivers():
    X, _, _ = features.prepare(_sample().head(50))
    why = scoring.explain_rows(X.head(3), top=4)
    assert len(why) == 3 and all(w and "text" in w[0] and w[0]["direction"] in ("up", "down") for w in why)

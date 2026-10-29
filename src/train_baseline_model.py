"""
Layer 4 (Week 5): Baseline detection model.

Trains an XGBoost classifier on the Week 4 feature set, predicting
`any_attack_flag` (the combined label: PaySim's own fraud flag OR any of
the three Ghana-specific attack patterns from Week 3). Predicting the
combined label, not just isFraud, is a deliberate choice: this system is
titled an intrusion AND fraud detection system, so the target should
cover both, not just PaySim's narrower financial-fraud definition.

Class imbalance handling: any_attack_flag is still a minority class
(~7.2%), so this uses XGBoost's scale_pos_weight rather than naive
accuracy-driven training, and reports precision/recall/F1/AUC-PR instead
of plain accuracy, since accuracy is meaningless on an imbalanced target
(predicting "not an attack" for everything would already score >92%).

Usage:
    python src/train_baseline_model.py --features data/processed/features.csv
"""
import argparse
import json
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    precision_recall_fscore_support, roc_auc_score, average_precision_score,
    confusion_matrix, classification_report,
)
from xgboost import XGBClassifier
import joblib

FEATURE_COLS = [
    "amount", "amount_log", "oldbalanceOrg", "newbalanceOrig",
    "oldbalanceDest", "newbalanceDest", "balance_error_orig", "balance_error_dest",
    "hour_of_day", "is_night",
    "orig_txn_count_so_far", "orig_avg_amount_so_far", "amount_to_avg_ratio",
    "orig_distinct_devices", "orig_ever_sim_change", "dest_distinct_senders",
]
CATEGORICAL_COL = "type"
TARGET_COL = "any_attack_flag"


def load_and_prepare(features_path: str):
    df = pd.read_csv(
        features_path,
        dtype={
            "amount": "float32", "oldbalanceOrg": "float32", "newbalanceOrig": "float32",
            "oldbalanceDest": "float32", "newbalanceDest": "float32",
            "balance_error_orig": "float32", "balance_error_dest": "float32",
            "amount_log": "float32", "orig_avg_amount_so_far": "float32",
            "amount_to_avg_ratio": "float32", "hour_of_day": "int8", "is_night": "int8",
            "orig_txn_count_so_far": "int32", "orig_distinct_devices": "int16",
            "orig_ever_sim_change": "int8", "dest_distinct_senders": "int32",
            "type": "category", "any_attack_flag": "int8",
        },
    )
    type_dummies = pd.get_dummies(df[CATEGORICAL_COL], prefix="type", dtype=np.int8)
    X = pd.concat([df[FEATURE_COLS], type_dummies], axis=1)
    y = df[TARGET_COL]
    return X, y


def run(features_path: str, model_out: str, metrics_out: str, seed: int = 42):
    t0 = time.time()
    X, y = load_and_prepare(features_path)
    print(f"[{time.time()-t0:.1f}s] loaded {len(X):,} rows, {X.shape[1]} features, "
          f"positive rate {y.mean()*100:.3f}%")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )
    print(f"[{time.time()-t0:.1f}s] split: {len(X_train):,} train / {len(X_test):,} test")

    # class imbalance handling: weight the minority (attack) class by the
    # ratio of negatives to positives in the training set, rather than
    # resampling, which would mean duplicating or discarding real transactions
    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    print(f"[{time.time()-t0:.1f}s] scale_pos_weight = {scale_pos_weight:.2f}")

    model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        tree_method="hist",
        scale_pos_weight=scale_pos_weight,
        eval_metric="aucpr",
        n_jobs=2,
        random_state=seed,
    )
    model.fit(X_train, y_train)
    print(f"[{time.time()-t0:.1f}s] model trained")

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    precision, recall, f1, _ = precision_recall_fscore_support(y_test, y_pred, average="binary")
    auc_roc = roc_auc_score(y_test, y_proba)
    auc_pr = average_precision_score(y_test, y_proba)
    cm = confusion_matrix(y_test, y_pred).tolist()

    metrics = {
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "auc_roc": round(float(auc_roc), 4),
        "auc_pr": round(float(auc_pr), 4),
        "confusion_matrix": {"tn_fp_fn_tp": [cm[0][0], cm[0][1], cm[1][0], cm[1][1]]},
        "n_train": len(X_train),
        "n_test": len(X_test),
        "positive_rate_pct": round(float(y.mean() * 100), 3),
    }

    print(f"[{time.time()-t0:.1f}s] evaluation on held-out test set:")
    print(json.dumps(metrics, indent=2))
    print("\n" + classification_report(y_test, y_pred, target_names=["normal", "attack"]))

    joblib.dump({"model": model, "feature_columns": list(X.columns)}, model_out)
    # checksum the backend verifies before loading (a joblib file is a pickle and can carry code)
    import hashlib
    with open(model_out, "rb") as fh, open(f"{model_out}.sha256", "w") as out:
        out.write(hashlib.sha256(fh.read()).hexdigest() + "
")
    with open(metrics_out, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[{time.time()-t0:.1f}s] saved model to {model_out}, metrics to {metrics_out}")

    # feature importance, useful for the supervisor conversation about
    # which engineered features actually matter
    importances = sorted(zip(X.columns, model.feature_importances_), key=lambda x: -x[1])
    print("\nTop 10 features by importance:")
    for name, score in importances[:10]:
        print(f"  {name:<28} {score:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=str, default="data/processed/features.csv")
    ap.add_argument("--model-out", type=str, default="backend/model.joblib")
    ap.add_argument("--metrics-out", type=str, default="reports/baseline_metrics.json")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    run(args.features, args.model_out, args.metrics_out, args.seed)

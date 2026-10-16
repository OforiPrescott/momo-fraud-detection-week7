"""
Precompute small, dashboard-ready summary files from the full labeled
dataset (6.36M rows, several hundred MB). The API layer serves these
small precomputed files rather than loading the full dataset into memory
on every request or at API startup, the same "aggregate once, serve
small" principle a production dashboard backed by a data warehouse would
use rather than querying raw transaction logs live.

Also writes a small scoring_sample.csv (Week 7): a few thousand real
transactions WITH their full engineered feature columns, so the API can
load a small file and run genuine live model inference on it, rather
than the full ~900MB features.csv.

Usage:
    python backend/precompute_dashboard_data.py
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
LABELED_PATH = os.path.join(HERE, "..", "data", "processed", "labeled_dataset.csv")
FEATURES_PATH = os.path.join(HERE, "..", "data", "processed", "features.csv")
OUT_DIR = os.path.join(HERE, "data")
SAMPLE_PER_FLAG = 200
SCORING_SAMPLE_SIZE = 5000


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = pd.read_csv(
        LABELED_PATH,
        dtype={
            "step": "int16", "amount": "float32", "type": "category",
            "isFraud": "int8", "isFlaggedFraud": "int8", "sim_swap_takeover": "int8",
            "pin_sharing_flag": "int8", "agent_collusion_flag": "int8", "any_attack_flag": "int8",
        },
    )
    print(f"Loaded {len(df):,} labeled transactions")

    # --- overall summary ---
    summary = {
        "total_transactions": int(len(df)),
        "flags": {
            "isFraud": int(df["isFraud"].sum()),
            "sim_swap_takeover": int(df["sim_swap_takeover"].sum()),
            "pin_sharing_flag": int(df["pin_sharing_flag"].sum()),
            "agent_collusion_flag": int(df["agent_collusion_flag"].sum()),
            "any_attack_flag": int(df["any_attack_flag"].sum()),
        },
        "any_attack_rate_pct": round(float(df["any_attack_flag"].mean() * 100), 3),
        "fraud_rate_by_type_pct": {
            k: round(float(v), 4)
            for k, v in (df.groupby("type", observed=True)["isFraud"].mean() * 100).to_dict().items()
        },
        "attack_rate_by_type_pct": {
            k: round(float(v), 4)
            for k, v in (df.groupby("type", observed=True)["any_attack_flag"].mean() * 100).to_dict().items()
        },
        "transaction_count_by_type": {
            k: int(v) for k, v in df["type"].value_counts().to_dict().items()
        },
    }
    with open(os.path.join(OUT_DIR, "dashboard_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("Wrote dashboard_summary.json")

    # --- sample flagged transactions per category, for the table view ---
    cols = ["step", "type", "amount", "nameOrig", "nameDest",
            "isFraud", "sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag"]

    samples = []
    for flag in ["sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag"]:
        subset = df[df[flag] == 1][cols].head(SAMPLE_PER_FLAG).copy()
        subset["matched_pattern"] = flag
        samples.append(subset)
    sample_df = pd.concat(samples, ignore_index=True)
    sample_df.to_csv(os.path.join(OUT_DIR, "flagged_samples.csv"), index=False)
    print(f"Wrote flagged_samples.csv ({len(sample_df):,} rows)")
    del df, samples, sample_df  # free before loading features.csv, both are large files

    # --- small feature-complete sample for live model scoring (Week 7) ---
    features = pd.read_csv(FEATURES_PATH)
    scoring_sample = features.sample(n=min(SCORING_SAMPLE_SIZE, len(features)), random_state=42)
    scoring_sample.to_csv(os.path.join(OUT_DIR, "scoring_sample.csv"), index=False)
    print(f"Wrote scoring_sample.csv ({len(scoring_sample):,} rows)")


if __name__ == "__main__":
    main()

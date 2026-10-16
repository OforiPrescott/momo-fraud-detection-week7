"""
Layer 3 (Week 4): Feature engineering.

Builds model-ready features from the labeled dataset, in three groups
matching the roadmap exactly:

1. VELOCITY features: how a transaction compares to the account's own
   recent history (prior transaction count, running average amount,
   ratio of this amount to that average).
2. DEVICE/LOCATION CHANGE features: how many distinct devices an account
   has used, and whether it has ever had a recorded SIM-change event
   (from the Week 2 access-event layer).
3. TIME-OF-DAY features: hour of day derived from PaySim's `step`, and a
   flag for unusual (late-night) hours.

IMPORTANT, to avoid label leakage: this does NOT use sim_swap_takeover,
pin_sharing_flag, or agent_collusion_flag as INPUT features, since those
are deterministic rule outputs computed from the same raw signals used
here. Including them as features would let a model just learn to re-detect
the rule's own thresholds rather than generalizing. They remain valid as
the TARGET label (any_attack_flag), just not as predictors.

Usage:
    python src/feature_engineering.py \
        --labeled data/processed/labeled_dataset.csv \
        --access-events data/processed/access_events_full.csv \
        --out data/processed/features.csv
"""
import argparse
import time

import numpy as np
import pandas as pd


def build_velocity_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-origin-account running stats, computed on transactions strictly
    BEFORE the current one (shifted), so no feature uses information from
    its own label's future. Requires df sorted by (nameOrig, step)."""
    grp = df.groupby("nameOrig")
    df["orig_txn_count_so_far"] = grp.cumcount().astype(np.int32)

    cum_amount = grp["amount"].cumsum() - df["amount"]  # sum strictly before this txn
    with np.errstate(invalid="ignore", divide="ignore"):
        avg_amount_so_far = cum_amount / df["orig_txn_count_so_far"].replace(0, np.nan)
    # first transaction for an account has no history: fall back to its own amount
    df["orig_avg_amount_so_far"] = avg_amount_so_far.fillna(df["amount"]).astype(np.float32)
    df["amount_to_avg_ratio"] = (df["amount"] / (df["orig_avg_amount_so_far"] + 1.0)).astype(np.float32)
    return df


def build_balance_consistency_features(df: pd.DataFrame) -> pd.DataFrame:
    """PaySim-specific engineered features used widely in the literature:
    the difference between what the ledger SHOULD show after a transaction
    and what it actually shows. A non-zero error often correlates with
    fraudulent transactions where balances weren't updated realistically."""
    df["balance_error_orig"] = (df["oldbalanceOrg"] - df["amount"] - df["newbalanceOrig"]).astype(np.float32)
    df["balance_error_dest"] = (df["oldbalanceDest"] + df["amount"] - df["newbalanceDest"]).astype(np.float32)
    df["amount_log"] = np.log1p(df["amount"]).astype(np.float32)
    return df


def build_time_of_day_features(df: pd.DataFrame) -> pd.DataFrame:
    df["hour_of_day"] = (df["step"] % 24).astype(np.int8)
    df["is_night"] = df["hour_of_day"].isin([0, 1, 2, 3, 4]).astype(np.int8)
    return df


def build_device_location_features(access_events_path: str) -> pd.DataFrame:
    """Static per-account features from the Week 2 access-event layer:
    total distinct devices ever seen, and whether a SIM-change was ever
    recorded. Computed with the same factorize-based approach Week 3 used
    to stay within memory, this box has 3.9GB RAM."""
    events = pd.read_csv(
        access_events_path,
        usecols=["account_id", "device_id", "sim_change_event"],
        dtype={"sim_change_event": "int8"},
    )
    acct_codes, acct_uniques = pd.factorize(events["account_id"])
    dev_codes, _ = pd.factorize(events["device_id"])
    small = pd.DataFrame({
        "acct_code": acct_codes.astype(np.int32),
        "dev_code": dev_codes.astype(np.int32),
        "sim_change_event": events["sim_change_event"].to_numpy(),
    }).drop_duplicates(["acct_code", "dev_code"])
    del events

    per_acct = small.groupby("acct_code").agg(
        orig_distinct_devices=("dev_code", "size"),
        orig_ever_sim_change=("sim_change_event", "max"),
    ).reset_index()
    per_acct["account_id"] = acct_uniques[per_acct["acct_code"].to_numpy()]
    return per_acct[["account_id", "orig_distinct_devices", "orig_ever_sim_change"]]


def build_destination_features(df: pd.DataFrame) -> pd.DataFrame:
    """Static per-destination feature: how many distinct senders a
    destination account has received from. High fan-in on CASH_OUT/TRANSFER
    is the raw signal agent-collusion detection is built from, exposing the
    count itself (not the Week-3 rule's flag) avoids leakage."""
    moves = df[df["type"].isin(["CASH_OUT", "TRANSFER"])]
    per_dest = moves.groupby("nameDest")["nameOrig"].nunique().rename("dest_distinct_senders").reset_index()
    return per_dest


def run(labeled_path: str, access_events_path: str, out_path: str):
    t0 = time.time()

    # Compute device/location features FIRST, from the access-event file alone,
    # before the (large) labeled transaction table is loaded. Loading both at
    # once is what caused an OOM kill on this box's 3.9GB RAM; Week 2 and
    # Week 3 both hit the same wall and were fixed the same way.
    device_features = build_device_location_features(access_events_path)
    print(f"[{time.time()-t0:.1f}s] device/location features computed from access events")

    df = pd.read_csv(
        labeled_path,
        dtype={
            "step": "int32", "amount": "float32", "type": "category",
            "isFraud": "int8", "isFlaggedFraud": "int8", "sim_swap_takeover": "int8",
            "pin_sharing_flag": "int8", "agent_collusion_flag": "int8", "any_attack_flag": "int8",
        },
    )
    print(f"[{time.time()-t0:.1f}s] loaded {len(df):,} labeled transactions")

    df = df.sort_values(["nameOrig", "step"]).reset_index(drop=True)
    df = build_velocity_features(df)
    print(f"[{time.time()-t0:.1f}s] velocity features built")

    df = build_balance_consistency_features(df)
    df = build_time_of_day_features(df)
    print(f"[{time.time()-t0:.1f}s] balance-consistency and time-of-day features built")

    df = df.merge(device_features, how="left", left_on="nameOrig", right_on="account_id").drop(columns=["account_id"])
    df["orig_distinct_devices"] = df["orig_distinct_devices"].fillna(1).astype(np.int16)
    df["orig_ever_sim_change"] = df["orig_ever_sim_change"].fillna(0).astype(np.int8)
    del device_features
    print(f"[{time.time()-t0:.1f}s] device/location features joined")

    dest_features = build_destination_features(df)
    df = df.merge(dest_features, how="left", on="nameDest")
    df["dest_distinct_senders"] = df["dest_distinct_senders"].fillna(0).astype(np.int32)
    del dest_features
    print(f"[{time.time()-t0:.1f}s] destination fan-in features joined")

    feature_cols = [
        "type", "amount", "amount_log", "oldbalanceOrg", "newbalanceOrig",
        "oldbalanceDest", "newbalanceDest", "balance_error_orig", "balance_error_dest",
        "hour_of_day", "is_night",
        "orig_txn_count_so_far", "orig_avg_amount_so_far", "amount_to_avg_ratio",
        "orig_distinct_devices", "orig_ever_sim_change", "dest_distinct_senders",
    ]
    target_cols = ["isFraud", "sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag", "any_attack_flag"]
    id_cols = ["step", "nameOrig", "nameDest"]

    out = df[id_cols + feature_cols + target_cols]
    out.to_csv(out_path, index=False)
    print(f"[{time.time()-t0:.1f}s] wrote {len(out):,} rows x {len(feature_cols)} features to {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", type=str, default="data/processed/labeled_dataset.csv")
    ap.add_argument("--access-events", type=str, default="data/processed/access_events_full.csv")
    ap.add_argument("--out", type=str, default="data/processed/features.csv")
    args = ap.parse_args()
    run(args.labeled, args.access_events, args.out)

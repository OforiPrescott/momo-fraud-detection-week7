"""
PaySim-style synthetic mobile money transaction generator.

Kaggle (where the canonical PaySim1 CSV lives) is not reachable from this
sandbox's network allowlist. Instead, this script generates a dataset with
the SAME schema and statistical shape as the Kaggle PaySim1 file, using the
official PaySim simulator's own calibration parameters (aggregatedTransactions.csv,
clientsProfiles.csv, initialBalancesDistribution.csv), cloned from
https://github.com/EdgarLopezPhD/PaySim (the project's own reference simulator).

Output columns match Kaggle PaySim1 exactly:
step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig,
nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud

Usage:
    python generate_paysim.py --scale 0.02 --out paysim_synthetic.csv --seed 42
"""
import argparse
import csv
import random
import numpy as np
import pandas as pd

PARAM_DIR = "paysim-sim/paramFiles"

# Fraud only ever occurs on these two transaction types in PaySim (documented behavior)
FRAUD_ELIGIBLE_TYPES = {"TRANSFER", "CASH_OUT"}
FRAUD_RATE = 0.0013          # ~ matches Kaggle PaySim1's ~0.13% fraud rate
FLAG_THRESHOLD = 200000      # PaySim's isFlaggedFraud rule: large TRANSFER attempts


def load_initial_balance_sampler(path):
    df = pd.read_csv(path)
    df["range_start"] = pd.to_numeric(df["range_start"], errors="coerce").fillna(0)
    df["range_end"] = pd.to_numeric(df["range_end"], errors="coerce")
    weights = df["percentage"].values
    weights = weights / weights.sum()

    def sample():
        row = df.sample(weights=weights).iloc[0]
        lo, hi = row["range_start"], row["range_end"]
        if pd.isna(hi):
            hi = lo + 1000
        return round(random.uniform(lo, hi), 2)

    return sample


def make_account_id(prefix):
    return f"{prefix}{random.randint(10**9, 10**10 - 1)}"


def generate(scale: float, seed: int, out_path: str):
    random.seed(seed)
    np.random.seed(seed)

    agg = pd.read_csv(f"{PARAM_DIR}/aggregatedTransactions.csv")
    sample_initial_balance = load_initial_balance_sampler(
        f"{PARAM_DIR}/initialBalancesDistribution.csv"
    )

    rows = []
    flagged_budget = 16  # PaySim1's Kaggle release has only 16 isFlaggedFraud rows total

    for _, bucket in agg.iterrows():
        action = bucket["action"]
        step = int(bucket["step"])
        count = max(0, int(round(bucket["count"] * scale)))
        if count == 0:
            continue
        avg, std = float(bucket["avg"]), float(bucket["std"])
        std = max(std, 1.0)

        amounts = np.random.normal(avg, std, count)
        amounts = np.clip(amounts, 1.0, None)

        for amt in amounts:
            amt = round(float(amt), 2)
            name_orig = make_account_id("C")
            is_fraud = 0
            is_flagged = 0

            if action in FRAUD_ELIGIBLE_TYPES and random.random() < FRAUD_RATE:
                is_fraud = 1
                old_orig = amt  # fraud pattern: drain the full balance
                new_orig = 0.0
                name_dest = make_account_id("C")
                old_dest = 0.0
                new_dest = amt
                if action == "TRANSFER" and amt > FLAG_THRESHOLD and flagged_budget > 0:
                    is_flagged = 1
                    flagged_budget -= 1
            else:
                old_orig = sample_initial_balance() + amt
                if action == "CASH_IN":
                    new_orig = old_orig + amt
                    old_orig = max(old_orig - amt, 0.0)
                    name_dest = make_account_id("C")
                    old_dest, new_dest = 0.0, 0.0
                elif action == "PAYMENT":
                    new_orig = max(old_orig - amt, 0.0)
                    name_dest = make_account_id("M")  # merchants: balances always 0
                    old_dest, new_dest = 0.0, 0.0
                else:  # CASH_OUT, DEBIT, TRANSFER (non-fraud)
                    new_orig = max(old_orig - amt, 0.0)
                    name_dest = make_account_id("C") if action != "DEBIT" else make_account_id("M")
                    old_dest = round(random.uniform(0, avg * 2), 2)
                    new_dest = old_dest + amt

            rows.append(
                [step, action, amt, name_orig, round(old_orig, 2), round(new_orig, 2),
                 name_dest, round(old_dest, 2), round(new_dest, 2), is_fraud, is_flagged]
            )

    random.shuffle(rows)

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
             "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud"]
        )
        writer.writerows(rows)

    n_fraud = sum(r[9] for r in rows)
    print(f"Wrote {len(rows):,} rows to {out_path}")
    print(f"Fraud rows: {n_fraud:,} ({n_fraud/len(rows)*100:.3f}%)")
    print(f"Flagged fraud rows: {sum(r[10] for r in rows)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=0.02, help="Fraction of full calibrated volume to generate")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="paysim_synthetic.csv")
    args = ap.parse_args()
    generate(args.scale, args.seed, args.out)

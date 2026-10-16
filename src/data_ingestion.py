"""
Layer 1: Data ingestion + EDA

Loads the PaySim transaction backbone, profiles it (volume, amount
distributions, fraud class balance, per-type breakdown), and saves
summary figures to reports/figures/ for the weekly briefing.

Usage:
    python src/data_ingestion.py --input data/raw/paysim_synthetic.csv
"""
import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

FIGURES_DIR = "reports/figures"


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    expected_cols = {
        "step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
        "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud",
    }
    missing = expected_cols - set(df.columns)
    if missing:
        raise ValueError(f"Input file is missing expected PaySim columns: {missing}")
    return df


def profile(df: pd.DataFrame) -> dict:
    n = len(df)
    n_fraud = int(df["isFraud"].sum())
    summary = {
        "n_rows": n,
        "n_fraud": n_fraud,
        "fraud_rate_pct": round(n_fraud / n * 100, 4),
        "n_flagged_fraud": int(df["isFlaggedFraud"].sum()),
        "n_unique_orig_accounts": df["nameOrig"].nunique(),
        "n_unique_dest_accounts": df["nameDest"].nunique(),
        "step_range": (int(df["step"].min()), int(df["step"].max())),
        "type_counts": df["type"].value_counts().to_dict(),
        "fraud_by_type": df[df["isFraud"] == 1]["type"].value_counts().to_dict(),
        "amount_stats": df["amount"].describe().to_dict(),
    }
    return summary


def print_summary(summary: dict):
    print("=" * 60)
    print("PAYSIM DATA PROFILE")
    print("=" * 60)
    print(f"Total transactions:      {summary['n_rows']:,}")
    print(f"Fraud transactions:      {summary['n_fraud']:,} ({summary['fraud_rate_pct']}%)")
    print(f"Flagged fraud:           {summary['n_flagged_fraud']:,}")
    print(f"Unique origin accounts:  {summary['n_unique_orig_accounts']:,}")
    print(f"Unique dest accounts:    {summary['n_unique_dest_accounts']:,}")
    print(f"Step (time unit) range:  {summary['step_range']}")
    print("\nTransaction counts by type:")
    for t, c in summary["type_counts"].items():
        print(f"  {t:<10} {c:,}")
    print("\nFraud counts by type (fraud only occurs on TRANSFER/CASH_OUT):")
    for t, c in summary["fraud_by_type"].items():
        print(f"  {t:<10} {c:,}")
    print("\nAmount distribution:")
    for k, v in summary["amount_stats"].items():
        print(f"  {k:<10} {v:,.2f}")
    print("=" * 60)


def make_figures(df: pd.DataFrame, out_dir: str = FIGURES_DIR):
    os.makedirs(out_dir, exist_ok=True)

    # 1. Class balance (log scale, since fraud is a tiny sliver)
    fig, ax = plt.subplots(figsize=(5, 4))
    df["isFraud"].value_counts().plot(kind="bar", ax=ax, color=["#4C72B0", "#C44E52"])
    ax.set_yscale("log")
    ax.set_xticklabels(["Legit", "Fraud"], rotation=0)
    ax.set_title("Class balance (log scale)")
    fig.tight_layout()
    fig.savefig(f"{out_dir}/class_balance.png", dpi=150)
    plt.close(fig)

    # 2. Transaction type distribution
    fig, ax = plt.subplots(figsize=(6, 4))
    df["type"].value_counts().plot(kind="bar", ax=ax, color="#4C72B0")
    ax.set_title("Transactions by type")
    fig.tight_layout()
    fig.savefig(f"{out_dir}/type_distribution.png", dpi=150)
    plt.close(fig)

    # 3. Fraud rate by type
    fraud_rate_by_type = df.groupby("type")["isFraud"].mean() * 100
    fig, ax = plt.subplots(figsize=(6, 4))
    fraud_rate_by_type.plot(kind="bar", ax=ax, color="#C44E52")
    ax.set_ylabel("Fraud rate (%)")
    ax.set_title("Fraud rate by transaction type")
    fig.tight_layout()
    fig.savefig(f"{out_dir}/fraud_rate_by_type.png", dpi=150)
    plt.close(fig)

    # 4. Amount distribution, legit vs fraud (log scale)
    fig, ax = plt.subplots(figsize=(6, 4))
    df[df.isFraud == 0]["amount"].clip(upper=df["amount"].quantile(0.99)).hist(
        bins=50, alpha=0.6, label="Legit", ax=ax, color="#4C72B0"
    )
    df[df.isFraud == 1]["amount"].hist(bins=50, alpha=0.6, label="Fraud", ax=ax, color="#C44E52")
    ax.set_yscale("log")
    ax.set_xlabel("Amount")
    ax.set_title("Amount distribution: legit vs fraud")
    ax.legend()
    fig.tight_layout()
    fig.savefig(f"{out_dir}/amount_distribution.png", dpi=150)
    plt.close(fig)

    # 5. Transaction volume over time (step)
    fig, ax = plt.subplots(figsize=(8, 4))
    df.groupby("step").size().plot(ax=ax, color="#4C72B0")
    ax.set_xlabel("Step (hour)")
    ax.set_ylabel("Transaction count")
    ax.set_title("Transaction volume over time")
    fig.tight_layout()
    fig.savefig(f"{out_dir}/volume_over_time.png", dpi=150)
    plt.close(fig)

    print(f"\nSaved 5 figures to {out_dir}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=str, default="data/raw/paysim_synthetic.csv")
    ap.add_argument("--figures", action="store_true", help="Also generate EDA figures")
    args = ap.parse_args()

    data = load_data(args.input)
    result = profile(data)
    print_summary(result)

    if args.figures:
        make_figures(data)

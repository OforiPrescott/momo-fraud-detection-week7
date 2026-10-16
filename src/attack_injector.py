"""
Layer 1c (Week 3): Ghana-specific attack scenario labeling.

Joins the transaction layer (paysim_real.csv) with the access-event layer
(access_events_full.csv) on account_id/step, and labels three attack
patterns documented as common MoMo fraud vectors in Ghana. These labels
are ADDITIONAL to PaySim's own isFraud column, which only covers
financial fraud, not intrusion/account-takeover behavior.

Patterns
--------
1. SIM-swap takeover: a high-value CASH_OUT/TRANSFER occurring in the
   same hour (step) that a sim_change_event was recorded for that
   account. This is the classic MoMo takeover pattern: an attacker
   swaps the victim's SIM, then immediately drains the account.

2. PIN-sharing abuse: an account transacting from 2+ distinct device_ids
   within the same day, with NO recorded sim_change_event. A legitimate
   SIM swap is a recorded event; multiple devices without one suggests
   the PIN/credentials were shared or compromised without the owner's
   knowledge.

3. Agent collusion: a destination account (an agent, in MoMo terms)
   receiving many structured amounts just under PaySim's flagging
   threshold (200,000) from a wide set of distinct senders. This mirrors
   the documented "structuring" pattern used to stay under reporting
   thresholds with the help of a colluding agent.

All three checks are written as vectorized groupby/merge operations,
not row-by-row loops, since Week 2 already showed what happens to
row-by-row processing at PaySim's scale (6.35M accounts, 6.36M
transactions).

Usage:
    python src/attack_injector.py \
        --transactions data/raw/paysim_real.csv \
        --access-events data/processed/access_events_full.csv \
        --out data/processed/labeled_dataset.csv
"""
import argparse
import time

import numpy as np
import pandas as pd

HIGH_VALUE_THRESHOLD = 100_000       # SIM-swap takeover: "drain" amount
STRUCTURING_LOW = 150_000            # Agent collusion: structured-amount band
STRUCTURING_HIGH = 200_000           # matches PaySim's own isFlaggedFraud threshold
AGENT_MIN_SENDERS = 20               # distinct senders to call a destination a "hub"
AGENT_MIN_STRUCTURED_TXNS = 5        # structured transactions to call it collusion


def flag_pin_sharing(events: pd.DataFrame) -> pd.DataFrame:
    """Per account-day: flag accounts using 2+ distinct devices with no
    recorded sim_change_event that day. Returns one row per (account, day).

    Memory note: naive groupby(...).nunique() on the raw string device_id
    column over 15.9M rows was enough to trigger an OOM kill on this box.
    Factorizing account_id and device_id into integer codes first (same
    idea as Week 2's vectorization fix) keeps this well within budget.
    """
    acct_codes, acct_uniques = pd.factorize(events["account_id"])
    dev_codes, _ = pd.factorize(events["device_id"])
    day = (events["step"] // 24).to_numpy()
    sim_change = events["sim_change_event"].to_numpy()

    small = pd.DataFrame({
        "acct_code": acct_codes.astype(np.int32),
        "day": day.astype(np.int16),
        "dev_code": dev_codes.astype(np.int32),
        "sim_change_event": sim_change,
    })
    # drop duplicate (account, day, device) combos before counting, far
    # fewer rows than the raw event log, which shrinks the groupby that follows
    small = small.drop_duplicates(["acct_code", "day", "dev_code"])

    daily = small.groupby(["acct_code", "day"]).agg(
        distinct_devices=("dev_code", "size"),
        any_sim_change=("sim_change_event", "max"),
    ).reset_index()

    daily["pin_sharing_flag"] = (
        (daily["distinct_devices"] >= 2) & (daily["any_sim_change"] == 0)
    ).astype(np.int8)
    daily["account_id"] = acct_uniques[daily["acct_code"].to_numpy()]
    return daily[["account_id", "day", "pin_sharing_flag"]]


def flag_agent_collusion(tx: pd.DataFrame) -> pd.DataFrame:
    """Per destination account: flag as a suspected colluding agent if it
    receives structured amounts (just under the flagging threshold) from
    a wide base of distinct senders. Returns one row per destination."""
    cash_moves = tx[tx["type"].isin(["CASH_OUT", "TRANSFER"])].copy()
    cash_moves["is_structured"] = cash_moves["amount"].between(STRUCTURING_LOW, STRUCTURING_HIGH)

    per_dest = cash_moves.groupby("nameDest").agg(
        distinct_senders=("nameOrig", "nunique"),
        structured_txn_count=("is_structured", "sum"),
    ).reset_index()

    per_dest["agent_collusion_flag"] = (
        (per_dest["distinct_senders"] >= AGENT_MIN_SENDERS)
        & (per_dest["structured_txn_count"] >= AGENT_MIN_STRUCTURED_TXNS)
    ).astype(np.int8)
    return per_dest[["nameDest", "agent_collusion_flag"]]


def run(transactions_path: str, access_events_path: str, out_path: str):
    """
    Memory strategy: this box has 3.9GB RAM. The full transaction table
    (~1.9GB loaded) and the full access-event table (~1.9GB loaded) don't
    both fit alongside working space for groupbys, so this function never
    holds both at once: events are loaded and reduced down to two small
    per-account(-day) label tables FIRST, the events frame is freed, and
    only THEN is the (dtype-trimmed) transaction table loaded and merged
    against those small tables.
    """
    t0 = time.time()

    # --- Load access events, compute label tables, then free the events frame ---
    events = pd.read_csv(
        access_events_path,
        usecols=["account_id", "step", "device_id", "sim_change_event"],
        dtype={"step": "int16", "sim_change_event": "int8"},
    )
    print(f"[{time.time()-t0:.1f}s] loaded {len(events):,} access events")

    swap_hours = (
        events.loc[events["sim_change_event"] == 1, ["account_id", "step"]]
        .drop_duplicates()
        .assign(had_sim_change=1)
    )
    pin_sharing = flag_pin_sharing(events)
    del events
    print(f"[{time.time()-t0:.1f}s] access-event labels computed, events frame freed")

    # --- Now load transactions, with trimmed dtypes to keep this table small ---
    tx = pd.read_csv(
        transactions_path,
        dtype={
            "step": "int16", "amount": "float32", "type": "category",
            "isFraud": "int8", "isFlaggedFraud": "int8",
        },
    )
    print(f"[{time.time()-t0:.1f}s] loaded {len(tx):,} transactions")

    # --- Pattern 1: SIM-swap takeover ---
    tx = tx.merge(
        swap_hours, how="left", left_on=["nameOrig", "step"], right_on=["account_id", "step"]
    ).drop(columns=["account_id"])
    tx["had_sim_change"] = tx["had_sim_change"].fillna(0).astype(np.int8)
    tx["sim_swap_takeover"] = (
        tx["type"].isin(["CASH_OUT", "TRANSFER"])
        & (tx["amount"] > HIGH_VALUE_THRESHOLD)
        & (tx["had_sim_change"] == 1)
    ).astype(np.int8)
    tx = tx.drop(columns=["had_sim_change"])
    del swap_hours
    print(f"[{time.time()-t0:.1f}s] SIM-swap takeover flagged: {tx['sim_swap_takeover'].sum():,}")

    # --- Pattern 2: PIN-sharing (per account-day, joined back onto transactions by day) ---
    tx["day"] = tx["step"] // 24
    tx = tx.merge(pin_sharing, how="left", left_on=["nameOrig", "day"], right_on=["account_id", "day"])
    tx["pin_sharing_flag"] = tx["pin_sharing_flag"].fillna(0).astype(np.int8)
    tx = tx.drop(columns=["account_id", "day"])
    n_pin_accounts = pin_sharing["pin_sharing_flag"].sum()
    del pin_sharing
    print(f"[{time.time()-t0:.1f}s] PIN-sharing account-days flagged: {n_pin_accounts:,}, "
          f"transactions touched: {tx['pin_sharing_flag'].sum():,}")

    # --- Pattern 3: Agent collusion ---
    agent_flags = flag_agent_collusion(tx)
    tx = tx.merge(agent_flags, how="left", on="nameDest")
    tx["agent_collusion_flag"] = tx["agent_collusion_flag"].fillna(0).astype(np.int8)
    n_agent_hubs = agent_flags["agent_collusion_flag"].sum()
    print(f"[{time.time()-t0:.1f}s] suspected colluding agent accounts: {n_agent_hubs:,}, "
          f"transactions touched: {tx['agent_collusion_flag'].sum():,}")

    # --- Combined label: any attack pattern OR PaySim's own isFraud ---
    tx["any_attack_flag"] = (
        (tx["isFraud"] == 1)
        | (tx["sim_swap_takeover"] == 1)
        | (tx["pin_sharing_flag"] == 1)
        | (tx["agent_collusion_flag"] == 1)
    ).astype(np.int8)

    tx.to_csv(out_path, index=False)
    print(f"[{time.time()-t0:.1f}s] wrote labeled dataset: {out_path}")
    print(f"\nLabel summary out of {len(tx):,} transactions:")
    print(f"  isFraud (PaySim original):     {tx['isFraud'].sum():,}")
    print(f"  sim_swap_takeover:             {tx['sim_swap_takeover'].sum():,}")
    print(f"  pin_sharing_flag:              {tx['pin_sharing_flag'].sum():,}")
    print(f"  agent_collusion_flag:          {tx['agent_collusion_flag'].sum():,}")
    print(f"  any_attack_flag (combined):    {tx['any_attack_flag'].sum():,} "
          f"({tx['any_attack_flag'].mean()*100:.3f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--transactions", type=str, default="data/raw/paysim_real.csv")
    ap.add_argument("--access-events", type=str, default="data/processed/access_events_full.csv")
    ap.add_argument("--out", type=str, default="data/processed/labeled_dataset.csv")
    args = ap.parse_args()
    run(args.transactions, args.access_events, args.out)

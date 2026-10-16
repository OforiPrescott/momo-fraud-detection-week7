"""
Layer 1b (Week 2 - finalized at full scale): synthetic access-event layer.

WHY THIS VERSION EXISTS
------------------------
Week 1's version used Faker (fake.uuid4(), fake.date_time_between(), one
Python function call per session) in a per-account loop. That worked fine
on a 491K-account synthetic sample, but crashed with an out-of-memory kill
when pointed at the real dataset's 6.35 million accounts, both when
building one big in-memory list of dicts, and even after switching to a
row-by-row CSV writer (the row-by-row version technically avoided the
OOM, but was too slow to finish in a single run against the full dataset).

This version fixes both problems with two standard big-data techniques:

1. Vectorization: instead of calling a Python function once per session
   (15.9M times), attributes are generated as whole numpy arrays in one
   shot (home_city_idx, home_telco_idx, sim-swap flags, coordinates,
   timestamps), then indexed/broadcast into place. This is 100x+ faster
   than the per-row Faker approach.
2. Chunking: accounts are processed in batches of 500,000 rather than
   all 6.35M at once, with each batch's events appended to disk
   immediately and discarded from memory. Peak memory stays roughly
   constant regardless of how large the input dataset grows, which is
   the same principle a production system would need if it had to
   process a telco's real transaction volume instead of a fixed CSV.

Result: full 6.35M-account real dataset -> 15,885,668 access events in
about 64 seconds, with no memory crash.

Usage:
    python src/access_event_generator.py \
        --transactions data/raw/paysim_real.csv \
        --out data/processed/access_events_full.csv
"""
import argparse
import time

import numpy as np
import pandas as pd

GHANA_REGIONS = [
    ("Accra", "Greater Accra"), ("Kumasi", "Ashanti"), ("Tamale", "Northern"),
    ("Sekondi-Takoradi", "Western"), ("Cape Coast", "Central"), ("Ho", "Volta"),
    ("Koforidua", "Eastern"), ("Sunyani", "Bono"), ("Wa", "Upper West"),
    ("Bolgatanga", "Upper East"),
]
CITY_COORDS = {
    "Accra": (5.6037, -0.1870), "Kumasi": (6.6885, -1.6244), "Tamale": (9.4034, -0.8424),
    "Sekondi-Takoradi": (4.9344, -1.7554), "Cape Coast": (5.1053, -1.2466), "Ho": (6.6110, 0.4708),
    "Koforidua": (6.0940, -0.2610), "Sunyani": (7.3399, -2.3268), "Wa": (10.0601, -2.5099),
    "Bolgatanga": (10.7856, -0.8514),
}
TELCOS = ["MTN", "Telecel", "AirtelTigo"]
N_REGIONS = len(GHANA_REGIONS)
CITIES = np.array([c for c, _ in GHANA_REGIONS])
REGIONS = np.array([r for _, r in GHANA_REGIONS])
TELCOS_ARR = np.array(TELCOS)
BASE_LAT = np.array([CITY_COORDS[c][0] for c, _ in GHANA_REGIONS])
BASE_LON = np.array([CITY_COORDS[c][1] for c, _ in GHANA_REGIONS])


def process_chunk(chunk_accounts, rng, sim_swap_rate, base_ts, pin_share_rate=0.015):
    """
    pin_share_rate adds a SECOND, independent device-change mechanism on
    top of the SIM-swap one: a session using a different device from the
    account's home device, but WITHOUT sim_change_event being set.

    This matters for detection logic downstream: a recorded SIM-swap
    (is_swap=True) represents a legitimate telco-visible event (the
    customer or an attacker actually swapped the SIM). A silent device
    change with no such record (is_pin_share=True here) represents the
    PIN-sharing/credential-sharing pattern, someone else transacting on
    the account without any formal SIM change ever happening. Without
    this second mechanism, every multi-device account in the dataset
    would always coincide with a recorded swap, making the PIN-sharing
    detection rule in attack_injector.py structurally unable to fire,
    exactly what happened in the first version of this generator.
    """
    n = len(chunk_accounts)
    home_city_idx = rng.integers(0, N_REGIONS, n)
    home_telco_idx = rng.integers(0, len(TELCOS), n)
    home_device_id = np.array([f"D-{h:012x}" for h in rng.integers(0, 2**48, n, dtype=np.uint64)])

    n_sessions = rng.integers(1, 5, n).astype(np.int32)
    total = int(n_sessions.sum())
    acct_idx = np.repeat(np.arange(n), n_sessions)

    is_swap = rng.random(total) < sim_swap_rate
    is_pin_share = (~is_swap) & (rng.random(total) < pin_share_rate)
    n_swap = int(is_swap.sum())
    n_pin_share = int(is_pin_share.sum())

    session_city_idx = home_city_idx[acct_idx]
    session_telco_idx = home_telco_idx[acct_idx]
    session_device = home_device_id[acct_idx]

    if n_swap or n_pin_share:
        session_city_idx = session_city_idx.copy()
        session_telco_idx = session_telco_idx.copy()
        session_device = session_device.copy()

    if n_swap:
        session_city_idx[is_swap] = rng.integers(0, N_REGIONS, n_swap)
        session_telco_idx[is_swap] = rng.integers(0, len(TELCOS), n_swap)
        session_device[is_swap] = [f"D-{h:012x}" for h in rng.integers(0, 2**48, n_swap, dtype=np.uint64)]

    if n_pin_share:
        # same city/telco as home (no telco-visible change), only the device differs
        session_device[is_pin_share] = [f"D-{h:012x}" for h in rng.integers(0, 2**48, n_pin_share, dtype=np.uint64)]

    lat = (BASE_LAT[session_city_idx] + rng.uniform(-0.05, 0.05, total)).round(5)
    lon = (BASE_LON[session_city_idx] + rng.uniform(-0.05, 0.05, total)).round(5)
    offset_hours = rng.integers(0, 24 * 90, total)
    login_ts = base_ts + pd.to_timedelta(offset_hours, unit="h")

    return pd.DataFrame({
        "account_id": chunk_accounts["nameOrig"].values[acct_idx],
        "step": chunk_accounts["step"].values[acct_idx],
        "login_timestamp": login_ts,
        "device_id": session_device,
        "telco": TELCOS_ARR[session_telco_idx],
        "city": CITIES[session_city_idx],
        "region": REGIONS[session_city_idx],
        "latitude": lat,
        "longitude": lon,
        "sim_change_event": is_swap.astype(np.int8),
    })


def generate(transactions_path, out_path, sim_swap_rate=0.03, seed=42, chunk_size=500_000):
    t0 = time.time()
    rng = np.random.default_rng(seed)
    base_ts = pd.Timestamp("2026-06-01")

    tx = pd.read_csv(transactions_path, usecols=["nameOrig", "step"])
    accounts = tx.drop_duplicates("nameOrig").reset_index(drop=True)
    del tx
    n_accounts = len(accounts)
    print(f"[{time.time()-t0:.1f}s] loaded {n_accounts:,} unique accounts")

    total_events = 0
    total_swaps = 0
    first = True
    n_chunks = (n_accounts + chunk_size - 1) // chunk_size

    for i in range(n_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, n_accounts)
        chunk = accounts.iloc[start:end]
        events = process_chunk(chunk, rng, sim_swap_rate, base_ts)
        events.to_csv(out_path, mode="w" if first else "a", header=first, index=False)
        first = False
        total_events += len(events)
        total_swaps += int(events["sim_change_event"].sum())
        print(f"[{time.time()-t0:.1f}s] chunk {i+1}/{n_chunks} done, "
              f"{end:,}/{n_accounts:,} accounts, {total_events:,} events so far")

    print(f"[{time.time()-t0:.1f}s] DONE. {total_events:,} events for {n_accounts:,} accounts, "
          f"{total_swaps:,} SIM-change events ({total_swaps/total_events*100:.2f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--transactions", type=str, default="data/raw/paysim_real.csv")
    ap.add_argument("--out", type=str, default="data/processed/access_events_full.csv")
    ap.add_argument("--sim-swap-rate", type=float, default=0.03)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chunk-size", type=int, default=500_000)
    args = ap.parse_args()
    generate(args.transactions, args.out, args.sim_swap_rate, args.seed, args.chunk_size)

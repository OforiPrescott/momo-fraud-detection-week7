"""
Layer 1b: Synthetic access-event layer.

PaySim only carries transaction data. Intrusion detection needs an
access/session layer on top: device ID, login timestamp, geolocation,
and SIM-change events, keyed to the same account IDs used in the
transaction data so the two layers can be joined downstream.

This uses Faker to generate plausible Ghana-context sessions (Ghanaian
cities/regions, MTN/Telecel/AirtelTigo-style device churn) for each
account seen in the PaySim file.

Usage:
    python src/access_event_generator.py \
        --transactions data/raw/paysim_synthetic.csv \
        --out data/processed/access_events.csv
"""
import argparse
import csv
import random
from datetime import timedelta

import pandas as pd
from faker import Faker

fake = Faker()

GHANA_REGIONS = [
    ("Accra", "Greater Accra"),
    ("Kumasi", "Ashanti"),
    ("Tamale", "Northern"),
    ("Sekondi-Takoradi", "Western"),
    ("Cape Coast", "Central"),
    ("Ho", "Volta"),
    ("Koforidua", "Eastern"),
    ("Sunyani", "Bono"),
    ("Wa", "Upper West"),
    ("Bolgatanga", "Upper East"),
]

TELCOS = ["MTN", "Telecel", "AirtelTigo"]

# Base coordinates per city, used to jitter a realistic-looking lat/lon per event
CITY_COORDS = {
    "Accra": (5.6037, -0.1870),
    "Kumasi": (6.6885, -1.6244),
    "Tamale": (9.4034, -0.8424),
    "Sekondi-Takoradi": (4.9344, -1.7554),
    "Cape Coast": (5.1053, -1.2466),
    "Ho": (6.6110, 0.4708),
    "Koforidua": (6.0940, -0.2610),
    "Sunyani": (7.3399, -2.3268),
    "Wa": (10.0601, -2.5099),
    "Bolgatanga": (10.7856, -0.8514),
}


def jitter_coords(city: str):
    lat, lon = CITY_COORDS[city]
    return round(lat + random.uniform(-0.05, 0.05), 5), round(lon + random.uniform(-0.05, 0.05), 5)


def generate_sessions_for_account(account_id: str, base_step: int, n_sessions: int, sim_swap_rate: float):
    """
    Generate a short login history for one account. Most accounts stay on
    one device/city/telco; a small fraction show a SIM-change event, which
    is the signal the intrusion-detection model needs to learn to flag.
    """
    home_city, home_region = random.choice(GHANA_REGIONS)
    home_device = fake.uuid4()
    home_telco = random.choice(TELCOS)
    base_time = fake.date_time_between(start_date="-90d", end_date="now")

    rows = []
    sim_changed = False
    for i in range(n_sessions):
        is_swap_event = (not sim_changed) and (random.random() < sim_swap_rate)
        if is_swap_event:
            sim_changed = True
            city, region = random.choice([c for c in GHANA_REGIONS if c[0] != home_city])
            device_id = fake.uuid4()
            telco = random.choice([t for t in TELCOS if t != home_telco])
        else:
            city, region = home_city, home_region
            device_id = home_device
            telco = home_telco

        lat, lon = jitter_coords(city)
        login_time = base_time + timedelta(hours=random.randint(0, 24 * 89), minutes=random.randint(0, 59))

        rows.append({
            "account_id": account_id,
            "step": base_step,
            "login_timestamp": login_time.isoformat(),
            "device_id": device_id,
            "telco": telco,
            "city": city,
            "region": region,
            "latitude": lat,
            "longitude": lon,
            "sim_change_event": int(is_swap_event),
        })
    return rows


def generate(transactions_path: str, out_path: str, sim_swap_rate: float, seed: int, max_accounts: int = None):
    """
    Streams output row-by-row instead of building one giant in-memory list.
    Real PaySim has ~6.35M unique accounts; holding every generated session
    as a Python dict in memory before writing was enough to trigger an
    out-of-memory kill on this box (3.9GB RAM). Streaming keeps memory flat
    regardless of dataset size, which matters here since a production
    telco-scale system would need to process this incrementally too.

    max_accounts caps how many accounts are processed, for fast dev runs
    against the full 6.3M-row real file without waiting on the entire set.
    """
    random.seed(seed)
    Faker.seed(seed)

    tx = pd.read_csv(transactions_path, usecols=["nameOrig", "step"])
    accounts = tx.drop_duplicates("nameOrig")[["nameOrig", "step"]]
    del tx  # free the full transaction frame, we only need the account list

    if max_accounts:
        accounts = accounts.sample(n=min(max_accounts, len(accounts)), random_state=seed)

    fieldnames = ["account_id", "step", "login_timestamp", "device_id", "telco",
                  "city", "region", "latitude", "longitude", "sim_change_event"]

    n_events = 0
    n_sim_change = 0

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for _, row in accounts.iterrows():
            n_sessions = random.randint(1, 4)
            sessions = generate_sessions_for_account(
                row["nameOrig"], int(row["step"]), n_sessions, sim_swap_rate
            )
            for s in sessions:
                writer.writerow(s)
                n_events += 1
                n_sim_change += s["sim_change_event"]

    print(f"Generated {n_events:,} access events for {accounts.shape[0]:,} accounts")
    print(f"SIM-change events: {n_sim_change:,} ({n_sim_change / n_events * 100:.2f}%)")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--transactions", type=str, default="data/raw/paysim_synthetic.csv")
    ap.add_argument("--out", type=str, default="data/processed/access_events.csv")
    ap.add_argument("--sim-swap-rate", type=float, default=0.03,
                     help="Fraction of accounts' session histories that include a SIM-change event")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-accounts", type=int, default=None,
                     help="Cap the number of accounts processed (for fast dev runs on large files)")
    args = ap.parse_args()
    generate(args.transactions, args.out, args.sim_swap_rate, args.seed, args.max_accounts)

"""
Raw data -> model-ready features (the Week 4 pipeline, applied to ANY dataset).

Takes whatever the user uploaded / queried / fetched, and produces:
  * X      the 21 features the trained model expects, in training order
  * frame  context columns for the dashboard (type, amount, accounts, labels...)
  * meta   how every feature was obtained: "provided", "derived" or "default"

The "default" bucket matters: when device data is missing the model's
strongest predictor (orig_distinct_devices, ~78% of importance) cannot be
computed, and the dashboard must say so instead of silently pretending.
"""
import numpy as np
import pandas as pd

from . import scoring
from .schema import (ALIASES, EVENT_ALIASES, KNOWN_TYPES, canonicalise_columns, normalise_types)

HIGH_VALUE = 100_000
STRUCT_LOW, STRUCT_HIGH = 150_000, 200_000
AGENT_MIN_SENDERS, AGENT_MIN_STRUCTURED = 20, 5
MOVES = ["CASH_OUT", "TRANSFER"]
LABEL_PREFERENCE = ["any_attack_flag", "isFraud", "label"]


def _num(df, col, default=0.0):
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def _binary(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        s = series.astype(str).str.strip().str.lower()
        return s.isin(["1", "true", "yes", "y", "fraud", "attack", "malicious", "suspicious", "1.0"]).astype("int8")
    return (pd.to_numeric(series, errors="coerce").fillna(0) > 0).astype("int8")


def _pin_sharing(ev: pd.DataFrame) -> pd.DataFrame:
    e = ev.assign(day=(ev["step"] // 24)).drop_duplicates(["account_id", "day", "device_id"])
    d = e.groupby(["account_id", "day"]).agg(n=("device_id", "size"), sim=("sim_change_event", "max")).reset_index()
    d["pin_sharing_flag"] = ((d["n"] >= 2) & (d["sim"] == 0)).astype("int8")
    return d[["account_id", "day", "pin_sharing_flag"]]


def prepare(df_raw: pd.DataFrame, events: pd.DataFrame | None = None):
    cols = scoring.feature_columns()
    notes, warnings = [], []
    df = canonicalise_columns(df_raw, feature_cols=cols)
    missing = [c for c in ("amount", "type") if c not in df.columns]
    if missing:
        raise ValueError(
            "Missing required column(s): " + ", ".join(missing) +
            ". Accepted names include 'amount' / 'amt' / 'value' and 'type' / 'transaction_type'."
        )

    df = df.reset_index(drop=True)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    neg = int((df["amount"] < 0).sum())
    if neg:  # the model only ever saw positive amounts; reversals/refunds are scored by their size
        df["amount"] = df["amount"].abs()
        warnings.append(f"{neg:,} rows had a negative amount (refund or reversal?); they were scored by their size.")
    bad = int(df["amount"].isna().sum())
    if bad:
        df = df[df["amount"].notna()].reset_index(drop=True)
        warnings.append(f"{bad:,} rows had a non-numeric amount and were skipped.")
    if df.empty:
        raise ValueError("No usable rows: every amount value was empty or non-numeric.")
    df["row_id"] = np.arange(len(df))
    df["type"], unknown = normalise_types(df["type"])
    if unknown:
        warnings.append(
            f"{unknown:,} rows have a transaction type outside CASH_IN / CASH_OUT / DEBIT / PAYMENT / TRANSFER; "
            "the model sees them as having no type."
        )

    src = {}  # feature -> provided | derived | default

    # --- time -----------------------------------------------------------------
    ts = pd.to_datetime(df["timestamp"], errors="coerce") if "timestamp" in df else None
    if "step" in df:
        df["step"] = _num(df, "step", 0).astype("int64")
    elif ts is not None and ts.notna().any():
        df["step"] = (((ts - ts.min()).dt.total_seconds() // 3600).fillna(0)).astype("int64") + 1
        notes.append("No 'step' column: hours since the earliest timestamp were used as the step.")
    else:
        df["step"] = 0
    if "hour_of_day" in df and df["hour_of_day"].notna().any():
        df["hour_of_day"] = _num(df, "hour_of_day").astype(int); src["hour_of_day"] = "provided"
    elif ts is not None and ts.notna().any():
        df["hour_of_day"] = ts.dt.hour.fillna(12).astype(int); src["hour_of_day"] = "derived"
    elif "step" in df_raw.columns or "step" in df.columns and df["step"].any():
        df["hour_of_day"] = (df["step"] % 24).astype(int); src["hour_of_day"] = "derived"
    else:
        df["hour_of_day"] = 12; src["hour_of_day"] = "default"
    if "is_night" in df and df["is_night"].notna().any():
        df["is_night"] = _binary(df["is_night"]); src["is_night"] = "provided"
    else:
        df["is_night"] = df["hour_of_day"].isin([0, 1, 2, 3, 4]).astype("int8")
        src["is_night"] = src["hour_of_day"]

    # --- balances -------------------------------------------------------------
    for c in ("oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest"):
        if c in df:
            df[c] = _num(df, c); src[c] = "provided"
        else:
            df[c] = 0.0; src[c] = "default"
    have_orig_bal = src["oldbalanceOrg"] == "provided" and src["newbalanceOrig"] == "provided"
    have_dest_bal = src["oldbalanceDest"] == "provided" and src["newbalanceDest"] == "provided"
    for name, ok, formula in (
        ("balance_error_orig", have_orig_bal, lambda d: d["oldbalanceOrg"] - d["amount"] - d["newbalanceOrig"]),
        ("balance_error_dest", have_dest_bal, lambda d: d["oldbalanceDest"] + d["amount"] - d["newbalanceDest"]),
    ):
        if name in df and df[name].notna().any():
            df[name] = _num(df, name); src[name] = "provided"
        elif ok:
            df[name] = formula(df); src[name] = "derived"
        else:
            df[name] = 0.0; src[name] = "default"
    src["amount"] = "provided"
    if "amount_log" in df and df["amount_log"].notna().any():
        df["amount_log"] = _num(df, "amount_log"); src["amount_log"] = "provided"
    else:
        df["amount_log"] = np.log1p(df["amount"].clip(lower=0)); src["amount_log"] = "derived"

    # --- velocity (needs sender id; strictly-before history, as in training) -----
    has_orig = "nameOrig" in df and df["nameOrig"].notna().any()
    has_dest = "nameDest" in df and df["nameDest"].notna().any()
    vel = ["orig_txn_count_so_far", "orig_avg_amount_so_far", "amount_to_avg_ratio"]
    if all(c in df and df[c].notna().any() for c in vel):
        for c in vel:
            df[c] = _num(df, c); src[c] = "provided"
    elif has_orig:
        s = df.sort_values(["nameOrig", "step", "row_id"], kind="stable")
        g = s.groupby("nameOrig", sort=False)
        cnt = g.cumcount()
        prior = g["amount"].cumsum() - s["amount"]
        avg = (prior / cnt.replace(0, np.nan)).fillna(s["amount"])
        df["orig_txn_count_so_far"] = cnt.reindex(df.index)
        df["orig_avg_amount_so_far"] = avg.reindex(df.index)
        df["amount_to_avg_ratio"] = df["amount"] / (df["orig_avg_amount_so_far"] + 1.0)
        for c in vel:
            src[c] = "derived"
        if "step" not in df_raw.columns and "timestamp" not in df.columns:
            notes.append("No time column: row order was treated as chronological for each sender's history.")
    else:
        df["orig_txn_count_so_far"] = 0
        df["orig_avg_amount_so_far"] = df["amount"]
        df["amount_to_avg_ratio"] = df["amount"] / (df["amount"] + 1.0)
        for c in vel:
            src[c] = "default"

    # --- destination fan-in ---------------------------------------------------
    if "dest_distinct_senders" in df and df["dest_distinct_senders"].notna().any():
        df["dest_distinct_senders"] = _num(df, "dest_distinct_senders"); src["dest_distinct_senders"] = "provided"
    elif has_orig and has_dest:
        fan = df[df["type"].isin(MOVES)].groupby("nameDest")["nameOrig"].nunique()
        df["dest_distinct_senders"] = df["nameDest"].map(fan).fillna(0)
        src["dest_distinct_senders"] = "derived"
    else:
        df["dest_distinct_senders"] = 0; src["dest_distinct_senders"] = "default"

    # --- device / SIM behaviour (the model's strongest signal) -------------------
    ev = None
    if events is not None and len(events):
        ev = canonicalise_columns(events, alias_map=EVENT_ALIASES)
        need = {"account_id", "device_id"}
        if not need.issubset(ev.columns):
            raise ValueError("The access-events file needs an account column and a device column "
                             "(e.g. account_id, device_id, sim_change_event, step).")
        ev["sim_change_event"] = _binary(ev["sim_change_event"]) if "sim_change_event" in ev else 0
        if "step" not in ev and "timestamp" in ev:
            t = pd.to_datetime(ev["timestamp"], errors="coerce")
            ev["step"] = (((t - t.min()).dt.total_seconds() // 3600).fillna(0)).astype(int) + 1
        ev["step"] = _num(ev, "step", 0).astype("int64") if "step" in ev else 0
        notes.append(f"Joined {len(ev):,} access events (device / SIM layer) on account id.")
    elif "device_id" in df and has_orig:
        ev = pd.DataFrame({
            "account_id": df["nameOrig"], "device_id": df["device_id"].astype(str),
            "sim_change_event": _binary(df["sim_change"]) if "sim_change" in df else 0, "step": df["step"],
        })
        notes.append("Device ids found in the main file were used to derive device behaviour.")

    if "orig_distinct_devices" in df and df["orig_distinct_devices"].notna().any():
        df["orig_distinct_devices"] = _num(df, "orig_distinct_devices", 1); src["orig_distinct_devices"] = "provided"
    elif ev is not None and has_orig:
        per = ev.drop_duplicates(["account_id", "device_id"]).groupby("account_id").agg(
            d=("device_id", "size"), s=("sim_change_event", "max"))
        per_sim = ev.groupby("account_id")["sim_change_event"].max()
        df["orig_distinct_devices"] = df["nameOrig"].map(per["d"]).fillna(1)
        src["orig_distinct_devices"] = "derived"
        if "orig_ever_sim_change" not in df or not df["orig_ever_sim_change"].notna().any():
            df["orig_ever_sim_change"] = df["nameOrig"].map(per_sim).fillna(0); src["orig_ever_sim_change"] = "derived"
    else:
        df["orig_distinct_devices"] = 1; src["orig_distinct_devices"] = "default"
    if "orig_ever_sim_change" in df and df["orig_ever_sim_change"].notna().any() and "orig_ever_sim_change" not in src:
        df["orig_ever_sim_change"] = _binary(df["orig_ever_sim_change"]); src["orig_ever_sim_change"] = "provided"
    elif "orig_ever_sim_change" not in src:
        if "sim_change" in df and has_orig:
            df["orig_ever_sim_change"] = df.groupby("nameOrig")["sim_change"].transform(lambda s: _binary(s).max())
            src["orig_ever_sim_change"] = "derived"
        else:
            df["orig_ever_sim_change"] = 0; src["orig_ever_sim_change"] = "default"

    # --- transaction type one-hot ------------------------------------------------
    for t in KNOWN_TYPES:
        df[f"type_{t}"] = (df["type"] == t).astype("int8")
        src[f"type_{t}"] = "provided"

    # --- rule labels (Week 3) when they can be re-derived --------------------------
    if "agent_collusion_flag" in df and df["agent_collusion_flag"].notna().any():
        df["agent_collusion_flag"] = _binary(df["agent_collusion_flag"])
    elif has_orig and has_dest:
        m = df[df["type"].isin(MOVES)]
        per = m.assign(st=m["amount"].between(STRUCT_LOW, STRUCT_HIGH)).groupby("nameDest").agg(
            s=("nameOrig", "nunique"), c=("st", "sum"))
        hub = ((per["s"] >= AGENT_MIN_SENDERS) & (per["c"] >= AGENT_MIN_STRUCTURED)).astype("int8")
        df["agent_collusion_flag"] = df["nameDest"].map(hub).fillna(0).astype("int8")
    if ev is not None and has_orig and df["step"].any():
        if "sim_swap_takeover" not in df:
            swaps = ev.loc[ev["sim_change_event"] == 1, ["account_id", "step"]].drop_duplicates().assign(_s=1)
            j = df[["nameOrig", "step"]].merge(swaps, how="left", left_on=["nameOrig", "step"],
                                               right_on=["account_id", "step"])
            df["sim_swap_takeover"] = ((j["_s"].fillna(0).to_numpy() == 1) & df["type"].isin(MOVES).to_numpy()
                                       & (df["amount"].to_numpy() > HIGH_VALUE)).astype("int8")
        if "pin_sharing_flag" not in df:
            pin = _pin_sharing(ev)
            j = df.assign(day=df["step"] // 24)[["nameOrig", "day"]].merge(
                pin, how="left", left_on=["nameOrig", "day"], right_on=["account_id", "day"])
            df["pin_sharing_flag"] = j["pin_sharing_flag"].fillna(0).astype("int8").to_numpy()
    for r in ("sim_swap_takeover", "pin_sharing_flag"):
        if r in df:
            df[r] = _binary(df[r])

    # --- ground-truth label, if the data has one ---------------------------------
    label_name = None
    for cand in LABEL_PREFERENCE:
        if cand in df and df[cand].notna().any():
            label_name = cand
            df["label"] = _binary(df[cand]) if cand != "label" else _binary(df["label"])
            break
    if label_name and df["label"].nunique() < 2:
        notes.append(f"Label column '{label_name}' has only one class, so accuracy cannot be measured.")
        label_name = None

    X = df[cols].astype("float64").clip(-3e38, 3e38).replace([np.inf, -np.inf], np.nan)
    bad_cells = int(X.isna().sum().sum())
    if bad_cells:  # impossible values must never reach the model as inf/NaN
        warnings.append(f"{bad_cells:,} input values were missing or impossible (infinite / too large) and were set to 0.")
        X = X.fillna(0)
    X = X.astype("float32")
    keep = [c for c in ["row_id", "step", "hour_of_day", "type", "amount", "nameOrig", "nameDest",
                        "oldbalanceOrg", "newbalanceOrig", "label", "isFraud", "any_attack_flag",
                        "sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag"] if c in df]
    frame = df[keep].copy()
    for c in cols:
        if c not in frame:
            frame[c] = X[c]

    imp = scoring.importances()
    coverage = sum(imp[c] for c in cols if src.get(c, "default") != "default")
    if src["orig_distinct_devices"] == "default":
        warnings.append(
            "No device information was supplied. Device behaviour is the model's strongest signal (about "
            f"{imp['orig_distinct_devices']*100:.0f}% of its importance), so scores rely on weaker financial signals. "
            "Add a device_id column, an access-events file, or an orig_distinct_devices column."
        )
    if not has_orig:
        warnings.append("No sender account column: per-sender history and repeat-offender checks were skipped.")
    if not has_dest:
        warnings.append("No receiver account column: fan-in and agent-collusion checks were skipped.")
    if not (have_orig_bal):
        warnings.append("Sender balances were not supplied, so ledger-mismatch and full-drain checks were skipped.")
    if src["hour_of_day"] == "default":
        warnings.append("No time information: time-of-day patterns could not be analysed.")

    meta = {
        "feature_sources": {c: src.get(c, "default") for c in cols},
        "importance": imp,
        "coverage_pct": round(coverage * 100, 1),
        "has_sender": bool(has_orig), "has_receiver": bool(has_dest), "has_balances": bool(have_orig_bal),
        "has_time": src["hour_of_day"] != "default",
        "has_devices": src["orig_distinct_devices"] != "default",
        "label_name": label_name,
        "rule_columns": [r for r in ("sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag") if r in frame],
        "notes": notes, "warnings": warnings,
    }
    return X, frame, meta

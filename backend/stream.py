"""
Real-time layer.

``Engine`` scores transactions ONE AT A TIME as they arrive, keeping
per-account history in memory so velocity, device and fan-in features are
computed exactly as in the batch pipeline (history strictly BEFORE the
current transaction, except devices/fan-in which count everything seen so
far). Every scored transaction is pushed to all connected dashboards through
Server-Sent Events (``Hub``).

Every signed-in user has their own ``Workspace`` (engine + hub + replay), so
one user's live feed, replay and threshold are never visible to another.

Two ways transactions arrive:
  1. POST /api/ingest   a real MoMo platform / webhook pushes transactions
  2. Replay             the dashboard replays a dataset at N transactions per
                        second, so the live view can be demonstrated without
                        a production feed

Every few seconds the recent window is re-analysed with the same insight
engine used for uploaded datasets, so interpretation and recommendations
update live.
"""
import asyncio
import json
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import insights, scoring
from .schema import KNOWN_TYPES, canonicalise_columns, normalise_types

MOVES = ("CASH_OUT", "TRANSFER")
MAX_ACCOUNTS = 500_000
WINDOW = 800
LOOP = None  # the server's event loop, set at startup; publishing from worker threads goes through it


class Hub:
    """Fan-out of events to every open dashboard connection."""

    def __init__(self):
        self.queues: set = set()

    def subscribe(self):
        q = asyncio.Queue(maxsize=2000)
        self.queues.add(q)
        return q

    def unsubscribe(self, q):
        self.queues.discard(q)

    def publish(self, event: str, data: dict):
        payload = (event, json.dumps(data, default=_json_default))

        def _put():
            for q in list(self.queues):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass  # a stalled client must never block scoring

        try:
            asyncio.get_running_loop()
            _put()  # already on the event loop (async endpoint or replay task)
        except RuntimeError:
            if LOOP is not None and not LOOP.is_closed():
                LOOP.call_soon_threadsafe(_put)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.threshold = 0.5
        self.accounts: "OrderedDict[str, list]" = OrderedDict()  # orig -> [count, sum, devices(set), sim]
        self.dest_senders: "OrderedDict[str, set]" = OrderedDict()
        self.window: deque = deque(maxlen=WINDOW)
        self.recent: deque = deque(maxlen=40)
        self.times: deque = deque(maxlen=2000)
        self.seq = 0
        self.total = 0
        self.total_flagged = 0
        self.dirty = False
        self.last_latency_ms = 0.0
        self.started = time.time()

    # -- state -----------------------------------------------------------------
    def reset(self):
        with self.lock:
            self.__init__()

    def _acct(self, key):
        a = self.accounts.get(key)
        if a is None:
            a = [0, 0.0, set(), 0]
            self.accounts[key] = a
            if len(self.accounts) > MAX_ACCOUNTS:
                self.accounts.popitem(last=False)
        return a

    # -- scoring ---------------------------------------------------------------
    def process(self, txns: list, source: str = "ingest"):
        """Score a batch (in arrival order). Returns list of result dicts."""
        t0 = time.perf_counter()
        cols = scoring.feature_columns()
        raw = canonicalise_columns(pd.DataFrame(txns), feature_cols=cols)
        if "amount" not in raw or "type" not in raw:
            raise ValueError("Each transaction needs at least 'amount' and 'type'.")
        raw["type"], _ = normalise_types(raw["type"])
        raw["amount"] = pd.to_numeric(raw["amount"], errors="coerce")
        now = datetime.now(timezone.utc)
        rows, extras = [], []
        with self.lock:
            for rec in raw.to_dict("records"):
                rec = {k: v for k, v in rec.items() if not (isinstance(v, float) and np.isnan(v))}
                if rec.get("amount") is None or rec["amount"] != rec["amount"]:
                    continue
                typ, amt = rec["type"], float(rec["amount"])
                orig, dest = rec.get("nameOrig"), rec.get("nameDest")
                # time of day: provided hour > timestamp > step > server clock (Ghana is on GMT = UTC)
                if "hour_of_day" in rec:
                    hour = int(rec["hour_of_day"])
                elif "timestamp" in rec and pd.notna(pd.to_datetime(rec["timestamp"], errors="coerce")):
                    hour = int(pd.to_datetime(rec["timestamp"]).hour)
                elif "step" in rec:
                    hour = int(rec["step"]) % 24
                else:
                    hour = now.hour
                f = {c: rec[c] for c in cols if c in rec}  # provided features win
                dev_given = "orig_distinct_devices" in rec or "device_id" in rec
                acct = self._acct(orig) if orig is not None else None
                if acct is not None:
                    if "orig_txn_count_so_far" not in f:
                        f["orig_txn_count_so_far"] = acct[0]
                    if "orig_avg_amount_so_far" not in f:
                        f["orig_avg_amount_so_far"] = acct[1] / acct[0] if acct[0] else amt
                    if "device_id" in rec:
                        acct[2].add(str(rec["device_id"]))
                    if "sim_change" in rec and str(rec["sim_change"]).lower() in ("1", "true", "yes", "1.0"):
                        acct[3] = 1
                    f.setdefault("orig_distinct_devices", max(len(acct[2]), 1))
                    f.setdefault("orig_ever_sim_change", acct[3])
                    acct[0] += 1
                    acct[1] += amt
                else:
                    f.setdefault("orig_txn_count_so_far", 0)
                    f.setdefault("orig_avg_amount_so_far", amt)
                    f.setdefault("orig_distinct_devices", 1)
                    f.setdefault("orig_ever_sim_change", 0)
                if dest is not None and orig is not None and typ in MOVES:
                    s = self.dest_senders.get(dest)
                    if s is None:
                        s = self.dest_senders[dest] = set()
                        if len(self.dest_senders) > MAX_ACCOUNTS:
                            self.dest_senders.popitem(last=False)
                    s.add(orig)
                f.setdefault("dest_distinct_senders", len(self.dest_senders.get(dest, ())) if dest is not None else 0)
                ob, nb = float(rec.get("oldbalanceOrg", 0) or 0), float(rec.get("newbalanceOrig", 0) or 0)
                od, nd = float(rec.get("oldbalanceDest", 0) or 0), float(rec.get("newbalanceDest", 0) or 0)
                bal = all(k in rec for k in ("oldbalanceOrg", "newbalanceOrig"))
                f.setdefault("amount", amt)
                f.setdefault("amount_log", float(np.log1p(max(amt, 0))))
                f.setdefault("oldbalanceOrg", ob); f.setdefault("newbalanceOrig", nb)
                f.setdefault("oldbalanceDest", od); f.setdefault("newbalanceDest", nd)
                f.setdefault("balance_error_orig", ob - amt - nb if bal else 0.0)
                f.setdefault("balance_error_dest", od + amt - nd if "newbalanceDest" in rec else 0.0)
                f.setdefault("hour_of_day", hour)
                f.setdefault("is_night", 1 if hour in (0, 1, 2, 3, 4) else 0)
                f.setdefault("amount_to_avg_ratio", amt / (float(f["orig_avg_amount_so_far"]) + 1.0))
                for t in KNOWN_TYPES:
                    f.setdefault(f"type_{t}", 1 if typ == t else 0)
                rows.append(f)
                extras.append({"type": typ, "amount": amt, "nameOrig": orig, "nameDest": dest, "hour": hour,
                               "dev": bool(dev_given), "bal": bal,
                               "oldbalanceOrg": ob, "newbalanceOrig": nb,
                               **{k: int(rec[k]) for k in ("label", "isFraud", "any_attack_flag", "sim_swap_takeover",
                                                           "pin_sharing_flag", "agent_collusion_flag")
                                  if k in rec and rec[k] == rec[k]}})
            if not rows:
                return []
            X = pd.DataFrame(rows)[cols].astype("float32")
            risk = scoring.score(X)
            flagged_idx = [i for i, r in enumerate(risk) if r >= self.threshold]
            why = {}
            if flagged_idx:
                for i, items in zip(flagged_idx, scoring.explain_rows(X.iloc[flagged_idx], top=4)):
                    why[i] = items
            out = []
            for i, r in enumerate(risk):
                self.seq += 1
                self.total += 1
                ex = extras[i]
                ev = {"id": self.seq, "ts": now.isoformat(timespec="milliseconds"), "type": ex["type"],
                      "amount": ex["amount"], "orig": ex["nameOrig"], "dest": ex["nameDest"], "risk": round(float(r), 4),
                      "flagged": bool(r >= self.threshold), "source": source}
                if "label" in ex or "any_attack_flag" in ex or "isFraud" in ex:
                    ev["actual"] = int(ex.get("any_attack_flag", ex.get("label", ex.get("isFraud", 0))))
                if ev["flagged"]:
                    self.total_flagged += 1
                    ev["why"] = why.get(i, [])
                    ev["features"] = {k: float(v) for k, v in X.iloc[i].items()}
                self.recent.appendleft(ev)
                self.times.append(time.time())
                self.window.append({**rows[i], **{k: v for k, v in ex.items() if k not in ("hour",)},
                                    "risk": float(r)})
                out.append(ev)
            self.dirty = True
            self.last_latency_ms = (time.perf_counter() - t0) * 1000 / max(len(out), 1)
        return out

    # -- live interpretation -------------------------------------------------------
    def live_analysis(self, cur=""):
        with self.lock:
            if len(self.window) < 20:
                return None
            df = pd.DataFrame(list(self.window))
            thr = self.threshold
            now = time.time()
            rate10 = sum(1 for t in self.times if now - t <= 10) / 10
            live = {"total": self.total, "flagged_total": self.total_flagged, "rate_per_sec": round(rate10, 2),
                    "latency_ms": round(self.last_latency_ms, 2), "window": len(df), "threshold": thr}
            self.dirty = False
        df["hour_of_day"] = df["hour_of_day"].astype(int)
        labelled = [c for c in ("any_attack_flag", "label", "isFraud") if c in df and df[c].notna().all()]
        label_name = labelled[0] if labelled else None
        if label_name:
            df["label"] = df[label_name].astype(int)
        imp = scoring.importances()
        has_dev = bool(df["dev"].any()) if "dev" in df else False
        cov = 100.0 if has_dev else (1 - imp["orig_distinct_devices"] - imp["orig_ever_sim_change"]) * 100
        warns = [] if has_dev else ["No device information is arriving with these transactions. Device behaviour is the "
                                    "model's strongest signal, so live scores lean on weaker financial signals."]
        rule_cols = [c for c in ("sim_swap_takeover", "pin_sharing_flag", "agent_collusion_flag")
                     if c in df and df[c].notna().all()]
        meta = {"has_time": True, "has_sender": df["nameOrig"].notna().any() if "nameOrig" in df else False,
                "has_receiver": df["nameDest"].notna().any() if "nameDest" in df else False,
                "has_balances": bool(df["bal"].any()) if "bal" in df else False, "has_devices": has_dev,
                "label_name": label_name if label_name and df["label"].nunique() > 1 else None,
                "rule_columns": rule_cols, "coverage_pct": round(cov, 1), "warnings": warns, "notes": []}
        y = df["label"].to_numpy() if meta["label_name"] else None
        curves = insights.build_curves(df["risk"].to_numpy(), df["amount"].to_numpy(dtype=float), y)
        res = insights.analyze(df, meta, curves, thr, cur=cur, light=False if len(df) <= 800 else True,
                               window_label=f"the {len(df)} most recent transactions")
        res["live"] = live
        return res

    def snapshot(self):
        with self.lock:
            return {"recent": list(self.recent)[:40], "threshold": self.threshold, "total": self.total,
                    "flagged_total": self.total_flagged}


class Replay:
    def __init__(self, engine: "Engine", hub: Hub):
        self.engine, self.hub = engine, hub
        self.task = None
        self.state = {"running": False, "rate": 0, "source": None, "sent": 0, "total": 0}

    def status(self):
        return dict(self.state)

    async def start(self, rows: list, rate: float, source: str, loop_forever: bool = True):
        await self.stop()
        self.state = {"running": True, "rate": rate, "source": source, "sent": 0, "total": len(rows)}
        self.hub.publish("replay", self.state)
        self.task = asyncio.create_task(self._run(rows, rate, loop_forever))

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.state["running"] = False
        self.hub.publish("replay", self.state)

    def set_rate(self, rate: float):
        self.state["rate"] = rate

    async def _run(self, rows, rate, loop_forever):
        loop = asyncio.get_running_loop()
        i, carry, last = 0, 0.0, time.time()
        try:
            while True:
                await asyncio.sleep(0.2)
                now = time.time()
                carry += (now - last) * self.state["rate"]
                last = now
                k = int(carry)
                if k < 1:
                    continue
                carry -= k
                batch = [rows[(i + j) % len(rows)] for j in range(k)]
                if not loop_forever and i + k >= len(rows):
                    batch = rows[i:]
                i += k
                res = await loop.run_in_executor(None, self.engine.process, batch, "replay")
                for ev in res:
                    self.hub.publish("txn", ev)
                self.state["sent"] += len(res)
                if not loop_forever and i >= len(rows):
                    break
        finally:
            self.state["running"] = False
            self.hub.publish("replay", self.state)


class Workspace:
    """One user's real-time state."""

    def __init__(self):
        self.engine = Engine()
        self.hub = Hub()
        self.replay = Replay(self.engine, self.hub)
        self.currency = ""
        self.touched = time.time()

    def idle(self):
        return not self.hub.queues and not self.replay.state["running"]


_workspaces: "dict[int, Workspace]" = {}
_ws_lock = threading.Lock()


def workspace(user_id: int) -> Workspace:
    with _ws_lock:
        ws = _workspaces.get(user_id)
        if ws is None:
            ws = _workspaces[user_id] = Workspace()
        ws.touched = time.time()
        return ws


def workspaces() -> list:
    with _ws_lock:
        return list(_workspaces.values())


def drop(user_id: int):
    with _ws_lock:
        ws = _workspaces.pop(user_id, None)
    if ws and ws.replay.task and LOOP is not None:
        LOOP.call_soon_threadsafe(ws.replay.task.cancel)


def evict_idle(max_idle: float = 2 * 3600):
    """Free the memory of users who have had no open dashboard and no replay for a while."""
    now = time.time()
    with _ws_lock:
        for uid in [u for u, w in _workspaces.items() if w.idle() and now - w.touched > max_idle]:
            del _workspaces[uid]

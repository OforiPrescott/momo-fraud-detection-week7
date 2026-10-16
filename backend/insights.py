"""
Automatic interpretation: turns scored transactions into findings and actions.

Everything here is deterministic and grounded in the numbers (no free-text
generation), so every sentence on the dashboard can be traced to a count
computed from the data. That is deliberate for a thesis: an analyst or
supervisor can ask "where does this come from?" and the evidence list
under each finding answers it.

Two public functions:
  build_curves(frame, risk, ...)  one-off per dataset: sorted-score curves, AUC
  analyze(...)                    per threshold: summary, charts, findings, recommendations
"""
import numpy as np
import pandas as pd

from . import scoring

REFERENCE_ATTACK_RATE = 7.2   # % of transactions labelled as attacks in the project's training data
GRID = np.round(np.arange(0, 1.0001, 0.01), 2)


# ------------------------------------------------------------------ formatting
def n_(x):
    return f"{int(round(x)):,}"


def pct(x, d=1):
    return f"{x:.{d}f}%"


def money(x, cur=""):
    x = float(x)
    a = abs(x)
    s = f"{x/1e9:.2f}B" if a >= 1e9 else f"{x/1e6:.2f}M" if a >= 1e6 else f"{x/1e3:.1f}K" if a >= 1e4 else f"{x:,.0f}"
    return f"{cur}{s}".strip()


def ev_(label, value):
    return {"label": label, "value": str(value)}


# ------------------------------------------------------------------ curves
def build_curves(risk: np.ndarray, amount: np.ndarray, y: np.ndarray | None):
    """Threshold curve over a 0..1 grid, computed once from sorted scores."""
    n = len(risk)
    order = np.argsort(risk)
    rs = risk[order]
    cum_amt = np.cumsum(amount[order][::-1])[::-1]
    idx = np.searchsorted(rs, GRID, side="left")
    safe = np.minimum(idx, n - 1)
    flagged = n - idx
    value = np.where(idx < n, cum_amt[safe], 0.0)
    out = {"t": GRID, "flagged": flagged, "value": value}
    auc = {}
    if y is not None:
        cum_pos = np.cumsum(y[order][::-1])[::-1]
        tp = np.where(idx < n, cum_pos[safe], 0)
        P = int(y.sum())
        prec = np.divide(tp, flagged, out=np.zeros(len(GRID)), where=flagged > 0)
        rec = tp / max(P, 1)
        f1 = np.divide(2 * prec * rec, prec + rec, out=np.zeros(len(GRID)), where=(prec + rec) > 0)
        out.update({"tp": tp, "precision": prec, "recall": rec, "f1": f1, "P": P})
        try:
            from sklearn.metrics import average_precision_score, roc_auc_score
            auc = {"auc_roc": float(roc_auc_score(y, risk)), "auc_pr": float(average_precision_score(y, risk))}
        except Exception:
            auc = {}
    out["auc"] = auc
    return out


def curve_points(c, n, y_present):
    pts = []
    for i in range(0, len(GRID), 2):
        if int(c["flagged"][i]) == 0:
            break  # beyond the highest score there is nothing to plot
        p = {"t": float(c["t"][i]), "flagged": int(c["flagged"][i]),
             "flagged_pct": round(float(c["flagged"][i]) / n * 100, 2)}
        if y_present:
            p.update({"precision": round(float(c["precision"][i]), 4), "recall": round(float(c["recall"][i]), 4),
                      "f1": round(float(c["f1"][i]), 4)})
        pts.append(p)
    return pts


def suggested_thresholds(c):
    if "precision" not in c:
        return None
    best = int(np.argmax(c["f1"]))
    out = {"best_f1": {"t": float(c["t"][best]), "precision": float(c["precision"][best]),
                       "recall": float(c["recall"][best])}}
    ok = np.where(c["recall"] >= 0.95)[0]
    if len(ok):
        i = int(ok[-1])
        out["recall_95"] = {"t": float(c["t"][i]), "precision": float(c["precision"][i]),
                            "recall": float(c["recall"][i])}
    ok = np.where(c["precision"] >= 0.90)[0]
    ok = ok[c["flagged"][ok] > 0] if len(ok) else ok
    if len(ok):
        i = int(ok[0])
        out["precision_90"] = {"t": float(c["t"][i]), "precision": float(c["precision"][i]),
                               "recall": float(c["recall"][i])}
    return out


# ------------------------------------------------------------------ analyze
def analyze(frame: pd.DataFrame, meta: dict, curves: dict, threshold: float, cur: str = "",
            light: bool = False, window_label: str | None = None) -> dict:
    t = float(threshold)
    n = len(frame)
    risk = frame["risk"].to_numpy()
    amount = frame["amount"].to_numpy(dtype=float)
    flag = risk >= t
    f = int(flag.sum())
    fpct = f / n * 100
    total_val = float(amount.sum())
    flag_val = float(amount[flag].sum())
    has_y = "label" in frame and meta.get("label_name")
    y = frame["label"].to_numpy() if has_y else None

    insights, recs = [], []

    def add(sev, id_, title, finding, evidence=None, rec_ids=None):
        insights.append({"id": id_, "severity": sev, "title": title, "finding": finding,
                         "evidence": evidence or [], "recs": rec_ids or []})

    def rec(id_, prio, title, detail, impact=None):
        recs.append({"id": id_, "priority": prio, "title": title, "detail": detail, "impact": impact})
        return id_

    # ---- response tiers (Recommendations: how many transactions land in each) ----
    hold_lo = max(t, 0.9)
    tiers_def = [("hold", "Hold and call the customer", risk >= hold_lo),
                 ("verify", "Ask for step-up verification", (risk >= t) & (risk < hold_lo)),
                 ("watch", "Allow, but watch", (risk >= min(0.3, t)) & (risk < t)),
                 ("allow", "Allow", risk < min(0.3, t))]
    tiers = [{"id": k, "label": lab, "count": int(m.sum()), "pct": round(m.sum() / n * 100, 2),
              "value": float(amount[m].sum())} for k, lab, m in tiers_def]
    critical = tiers[0]

    # ---- by type ----
    g = pd.DataFrame({"type": frame["type"].to_numpy(), "flag": flag, "amount": amount}).groupby("type")
    bt = g.agg(count=("flag", "size"), flagged=("flag", "sum")).reset_index()
    bt["flagged_value"] = g.apply(lambda d: d.loc[d["flag"], "amount"].sum(), include_groups=False).values
    bt["flagged_pct"] = bt["flagged"] / bt["count"] * 100
    by_type = \
        [{"type": r["type"], "count": int(r["count"]), "flagged": int(r["flagged"]),
          "flagged_pct": round(float(r["flagged_pct"]), 2), "flagged_value": float(r["flagged_value"])}
         for _, r in bt.sort_values("flagged", ascending=False).iterrows()]

    # ---- by hour ----
    by_hour = []
    if meta.get("has_time"):
        h = pd.DataFrame({"h": frame["hour_of_day"].to_numpy(), "flag": flag}).groupby("h")["flag"].agg(["size", "sum"])
        by_hour = [{"hour": int(i), "count": int(r["size"]), "flagged": int(r["sum"]),
                    "flagged_pct": round(r["sum"] / r["size"] * 100, 2)} for i, r in h.iterrows()]

    # ---- score histogram ----
    bins = np.linspace(0, 1, 21)
    hist = []
    all_h, _ = np.histogram(risk, bins=bins)
    if has_y:
        pos_h, _ = np.histogram(risk[y == 1], bins=bins)
    for i in range(20):
        row = {"bin": f"{bins[i]:.2f}", "count": int(all_h[i])}
        if has_y:
            row["attacks"] = int(pos_h[i]); row["normal"] = int(all_h[i] - pos_h[i])
        hist.append(row)

    summary = {
        "rows": n, "flagged": f, "flagged_pct": round(fpct, 3), "threshold": t,
        "total_value": total_val, "flagged_value": flag_val,
        "flagged_value_pct": round(flag_val / total_val * 100, 2) if total_val else 0.0,
        "mean_risk": round(float(risk.mean()), 4), "critical": critical["count"],
        "critical_value": critical["value"],
    }

    # ---- evaluation (labels present) ----
    evaluation, tp = None, 0
    if has_y:
        tp = int((flag & (y == 1)).sum()); fp = int(f - tp)
        P = int(y.sum()); fn = P - tp; tn = int(n - f - fn)
        prec = tp / f if f else 0.0
        rec_ = tp / P if P else 0.0
        f1 = 2 * prec * rec_ / (prec + rec_) if prec + rec_ else 0.0
        evaluation = {"label": meta["label_name"], "positives": P, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                      "precision": round(prec, 4), "recall": round(rec_, 4), "f1": round(f1, 4),
                      **{k: round(v, 4) for k, v in curves.get("auc", {}).items()},
                      "suggested": suggested_thresholds(curves)}

    # ---- repeat origins & receiver hubs ----
    top_origins, top_dest = [], []
    if meta.get("has_sender") and f:
        d = frame.loc[flag, ["nameOrig", "amount", "risk"]]
        o = d.groupby("nameOrig").agg(flagged=("risk", "size"), value=("amount", "sum"), max_risk=("risk", "max"))
        o = o[o["flagged"] >= 2].sort_values(["flagged", "value"], ascending=False).head(8)
        top_origins = [{"account": k, "flagged": int(r.flagged), "value": float(r.value),
                        "max_risk": round(float(r.max_risk), 3)} for k, r in o.iterrows()]
    if meta.get("has_receiver") and f:
        d = frame.loc[flag, ["nameDest", "nameOrig", "amount", "risk"]]
        dd = d.groupby("nameDest").agg(flagged=("risk", "size"), senders=("nameOrig", "nunique"),
                                       value=("amount", "sum"), avg_risk=("risk", "mean"))
        dd = dd[(dd["flagged"] >= 3) & (dd["senders"] >= 2)].sort_values(["flagged", "value"], ascending=False).head(8)
        top_dest = [{"account": k, "flagged": int(r.flagged), "senders": int(r.senders), "value": float(r.value),
                     "avg_risk": round(float(r.avg_risk), 3)} for k, r in dd.iterrows()]

    # ---- what drove the alerts (SHAP over a sample of flagged rows) ----
    drivers = []
    if not light and f:
        samp = frame.loc[flag].sample(min(1500, f), random_state=7)
        res = scoring.contribs(samp)
        if res is not None:
            mat = res[0]
            cols = scoring.feature_columns()
            mean_abs = np.abs(mat).mean(axis=0)
            mean_signed = mat.mean(axis=0)
            tot = mean_abs.sum() or 1
            for j in np.argsort(-mean_abs)[:6]:
                drivers.append({"feature": cols[j], "label": scoring.LABELS.get(cols[j], cols[j]),
                                "share": round(float(mean_abs[j] / tot * 100), 1),
                                "direction": "up" if mean_signed[j] >= 0 else "down"})

    # =============================== FINDINGS ===============================
    # 1. overall picture
    ratio = fpct / REFERENCE_ATTACK_RATE
    sev = "critical" if ratio >= 3 else "high" if ratio >= 1.5 else "medium" if ratio >= 0.7 else "good"
    ev = [ev_("Flagged transactions", f"{n_(f)} of {n_(n)} ({pct(fpct)})"),
          ev_("Value flagged", f"{money(flag_val, cur)} ({pct(summary['flagged_value_pct'])} of all value)"),
          ev_("Critical (risk >= %.2f)" % hold_lo, f"{n_(critical['count'])} transactions, {money(critical['value'], cur)}"),
          ev_("Reference", f"{REFERENCE_ATTACK_RATE}% of the project's training data carried an attack label")]
    r1 = rec("r_critical", "now", f"Work the {n_(critical['count'])} critical alerts first",
             f"Transactions scoring {hold_lo:.2f} or higher carry {money(critical['value'], cur)}. Place them on hold "
             "and confirm with the account holder by phone call-back before releasing funds.",
             f"{money(critical['value'], cur)} protected") if critical["count"] else None
    add(sev, "overall",
        f"{pct(fpct)} of transactions were flagged" if f else "No transactions crossed the alert threshold",
        (f"At a threshold of {t:.2f}, {n_(f)} of {n_(n)} transactions are flagged, holding {money(flag_val, cur)} of "
         f"{money(total_val, cur)} moved. " + ("That is well above the project's reference attack rate, so the data deserves a close look."
                                               if ratio >= 1.5 else
                                               "That is close to the rate seen in the project's training data."
                                               if ratio >= 0.7 else "That is below the project's reference rate; few transactions look risky at this setting.")),
        ev, [r1] if r1 else [])

    # 2. transaction type concentration
    cand = [b for b in by_type if b["count"] >= 30]
    if f and cand:
        top = max(cand, key=lambda b: b["flagged_pct"])
        lift = top["flagged_pct"] / fpct if fpct else 0
        if lift >= 1.25 and len(cand) > 1:
            share = top["flagged"] / f * 100
            rid = rec("r_type", "soon", f"Add a stricter control on {top['type'].replace('_', ' ').title()} transactions",
                      f"{top['type']} transactions are flagged {lift:.1f}x as often as average. Lower the per-transaction "
                      "and daily limit for accounts showing risk signals, or require a second factor above a set amount.",
                      f"{n_(top['flagged'])} alerts sit in this channel")
            add("high" if lift >= 2 else "medium", "type", f"{top['type']} carries the highest alert rate",
                f"{pct(top['flagged_pct'])} of {top['type']} transactions are flagged against {pct(fpct)} overall "
                f"({lift:.1f}x), and this type accounts for {pct(share, 0)} of all alerts.",
                [ev_(b["type"], f"{pct(b['flagged_pct'])} flagged of {n_(b['count'])}") for b in
                 sorted(cand, key=lambda b: -b["flagged_pct"])[:4]], [rid])

    # 3. late-night activity
    if meta.get("has_time") and f:
        hh = pd.DataFrame({"night": frame["hour_of_day"].isin([0, 1, 2, 3, 4]).to_numpy(), "flag": flag})
        nn, dn = hh[hh["night"]], hh[~hh["night"]]
        if len(nn) >= 30 and len(dn) >= 30:
            nr, dr = nn["flag"].mean() * 100, dn["flag"].mean() * 100
            if dr > 0 and nr / dr >= 1.5:
                rid = rec("r_night", "soon", "Tighten limits between 00:00 and 05:00",
                          "Apply a lower cash-out limit or an extra verification prompt overnight, when genuine "
                          "customers rarely transact and account-takeover attempts concentrate.",
                          f"{n_(int(nn['flag'].sum()))} overnight alerts")
                add("medium", "night", "Overnight transactions are riskier",
                    f"{pct(nr)} of transactions between 00:00 and 05:00 are flagged, against {pct(dr)} the rest of the day "
                    f"({nr/dr:.1f}x).", [ev_("Overnight transactions", n_(len(nn))),
                                          ev_("Overnight flagged", n_(int(nn['flag'].sum())))], [rid])

    # 4. device behaviour
    if meta.get("has_devices") and f:
        dv = frame["orig_distinct_devices"].to_numpy()
        multi = dv >= 2
        a, b_ = multi[flag].mean() * 100, multi[~flag].mean() * 100 if (~flag).any() else 0
        if a - b_ >= 10:
            rid = rec("r_device", "soon", "Require step-up verification when a second device appears",
                      "Send a one-time code to the registered number, or request biometric confirmation, the first time "
                      "an account transacts from a new device. Cap the number of devices active on one wallet.",
                      f"{n_(int((multi & flag).sum()))} alerts involve multi-device accounts")
            add("high", "device", "Multi-device accounts dominate the alerts",
                f"{pct(a, 0)} of flagged transactions come from accounts seen on 2 or more devices, compared with "
                f"{pct(b_, 0)} of unflagged ones. Device behaviour is the strongest signal in this model.",
                [ev_("Flagged, multi-device", pct(a, 0)), ev_("Unflagged, multi-device", pct(b_, 0))], [rid])

    # 5. SIM change + high-value cash movement
    if meta.get("has_devices") and f:
        sim = frame["orig_ever_sim_change"].to_numpy() >= 1
        hv = sim & flag & (amount > 100_000) & frame["type"].isin(["CASH_OUT", "TRANSFER"]).to_numpy()
        if hv.sum() >= 3:
            rid = rec("r_sim", "now", "Add a cooling-off period after a SIM change",
                      "For 24 to 72 hours after a SIM swap, cap cash-out and transfer amounts or require in-person "
                      "verification. This blocks the classic drain-after-swap takeover.",
                      f"{money(amount[hv].sum(), cur)} in {n_(hv.sum())} transactions")
            add("critical", "sim", "High-value cash-outs follow SIM changes",
                f"{n_(hv.sum())} flagged CASH_OUT/TRANSFER transactions above 100,000 come from accounts with a SIM "
                f"change on record, moving {money(amount[hv].sum(), cur)}. This matches the SIM-swap takeover pattern.",
                [ev_("Transactions", n_(hv.sum())), ev_("Value", money(amount[hv].sum(), cur))], [rid])

    # 6. full-balance drains
    if meta.get("has_balances") and f:
        ob = frame["oldbalanceOrg"].to_numpy(); nb = frame["newbalanceOrig"].to_numpy()
        mv = frame["type"].isin(["CASH_OUT", "TRANSFER"]).to_numpy()
        drain = mv & (ob > 0) & (nb == 0) & (amount >= 0.95 * ob)
        d_all, d_flag = int(drain.sum()), int((drain & flag).sum())
        if d_flag >= 5 and d_flag / f >= 0.05:
            rid = rec("r_drain", "now", "Hold full-balance withdrawals pending confirmation",
                      "When a CASH_OUT or TRANSFER empties the sender's wallet and other risk signals are present, "
                      "delay settlement briefly and confirm with the owner before releasing funds.",
                      f"{n_(d_flag)} account-emptying alerts")
            add("high", "drain", "Alerts include account-emptying withdrawals",
                f"{n_(d_flag)} flagged transactions take 95% or more of the sender's balance and leave the wallet at "
                f"zero ({pct(d_flag / f * 100, 0)} of alerts). Draining a wallet in one move is a typical takeover signature.",
                [ev_("Draining transactions overall", n_(d_all)), ev_("Of which flagged", n_(d_flag))], [rid])

    # 7. repeat senders
    if top_origins:
        worst = top_origins[0]
        rid = rec("r_repeat", "now", f"Freeze or review {len(top_origins)} repeatedly flagged accounts",
                  "Accounts with several alerts inside one dataset are the strongest takeover candidates. Suspend "
                  "outgoing transfers until the owner is reached through a verified channel.",
                  f"Top account: {worst['flagged']} alerts, {money(worst['value'], cur)}")
        add("high", "repeat", f"{len(top_origins)} accounts were flagged more than once",
            f"The most active, {worst['account']}, has {worst['flagged']} flagged transactions worth "
            f"{money(worst['value'], cur)}. Repeat alerts on one sender are rarely coincidence.",
            [ev_(o["account"], f"{o['flagged']} alerts, {money(o['value'], cur)}") for o in top_origins[:4]], [rid])

    # 8. receiver hubs
    if top_dest:
        w = top_dest[0]
        rid = rec("r_hub", "soon", f"Investigate {len(top_dest)} receiving accounts that collect flagged money",
                  "Review the receiving agents or wallets: audit float movement, check for structured amounts just below "
                  "limits, and suspend agent activity during the investigation where policy allows.",
                  f"Largest: {w['senders']} senders, {money(w['value'], cur)}")
        add("high", "hubs", "Flagged payments are converging on a few receivers",
            f"{w['account']} received {w['flagged']} flagged payments from {w['senders']} different senders "
            f"({money(w['value'], cur)}). Many senders paying one account is the shape of agent collusion or a mule account.",
            [ev_(d["account"], f"{d['flagged']} alerts from {d['senders']} senders") for d in top_dest[:4]], [rid])

    # 9. structuring band
    if f:
        band = (amount >= 150_000) & (amount <= 200_000)
        fb, ab = band[flag].mean() * 100, band.mean() * 100
        if band[flag].sum() >= 10 and fb >= 1.5 * max(ab, 0.1):
            rid = rec("r_struct", "soon", "Add a structuring rule just below the 200,000 limit",
                      "Alert on repeated amounts between 150,000 and 200,000 reaching the same receiver, and apply a "
                      "cumulative daily limit per receiver rather than only a per-transaction limit.",
                      f"{n_(int(band[flag].sum()))} alerts in the band")
            add("medium", "struct", "Amounts cluster just under the flagging limit",
                f"{pct(fb, 1)} of flagged transactions fall between 150,000 and 200,000, against {pct(ab, 1)} of all "
                "transactions. Splitting amounts to stay under a threshold is a recognised evasion tactic.",
                [ev_("Flagged in band", n_(int(band[flag].sum())))], [rid])

    # 10. borderline scores
    gray = int(((risk >= 0.3) & (risk < 0.7)).sum())
    if gray / n >= 0.02 and gray >= 20:
        add("info", "gray", "A share of transactions are borderline",
            f"{n_(gray)} transactions ({pct(gray / n * 100)}) score between 0.30 and 0.70. For these, asking for "
            "verification is gentler on genuine customers than blocking.",
            [ev_("Borderline (0.30 to 0.70)", n_(gray))])

    # 11. accuracy against labels
    if evaluation:
        p_, r_ = evaluation["precision"], evaluation["recall"]
        sg = evaluation["suggested"] or {}
        isfraud_only = meta["label_name"] == "isFraud"
        txt = (f"Against the '{meta['label_name']}' column, the model catches {pct(r_ * 100, 1)} of known attacks "
               f"({n_(evaluation['tp'])} of {n_(evaluation['positives'])}) and {pct(p_ * 100, 1)} of its alerts are "
               f"genuine. It missed {n_(evaluation['fn'])} and raised {n_(evaluation['fp'])} false alarms.")
        rids = []
        if r_ >= 0.95 and p_ < 0.6:
            txt += " It leans towards catching everything, at the cost of extra false alarms for analysts."
            if "best_f1" in sg and sg["best_f1"]["t"] > t:
                b = sg["best_f1"]
                rids.append(rec("r_thr", "plan", f"Raise the threshold to {b['t']:.2f} to cut false alarms",
                                f"Best balance on this data: precision {pct(b['precision'] * 100, 0)}, recall "
                                f"{pct(b['recall'] * 100, 0)}. Confirm with the team which costs more: a missed "
                                "attack or a wasted investigation.", "Fewer false alarms"))
        elif p_ >= 0.9 and r_ < 0.8:
            txt += " It is precise but lets some attacks through; lowering the threshold would catch more."
            if "recall_95" in sg:
                rids.append(rec("r_thr", "plan", f"Lower the threshold to {sg['recall_95']['t']:.2f} to catch more attacks",
                                f"At that setting recall reaches {pct(sg['recall_95']['recall'] * 100, 0)} with precision "
                                f"{pct(sg['recall_95']['precision'] * 100, 0)}.", "Fewer missed attacks"))
        if isfraud_only:
            txt += (" The labels cover financial fraud only, while the model also targets intrusion patterns "
                    "(SIM swap, PIN sharing, agent collusion), so some 'false alarms' may be real intrusions.")
        small = evaluation["positives"] < 30
        if small:
            txt += f" Only {n_(evaluation['positives'])} known attacks are in this data, so treat these figures as indicative."
        add("info" if small else "good" if (p_ >= .8 and r_ >= .8) else "medium", "accuracy",
            f"Measured accuracy: {pct(r_ * 100, 1)} recall, {pct(p_ * 100, 1)} precision", txt,
            [ev_("AUC-PR", evaluation.get("auc_pr", "n/a")), ev_("AUC-ROC", evaluation.get("auc_roc", "n/a")),
             ev_("Confusion (TN / FP / FN / TP)", f"{n_(evaluation['tn'])} / {n_(evaluation['fp'])} / "
                                                  f"{n_(evaluation['fn'])} / {n_(evaluation['tp'])}")], rids)

    # 12. rules vs model
    rules_vs_model = []
    for rcol, nm in (("sim_swap_takeover", "SIM-swap takeover"), ("pin_sharing_flag", "PIN-sharing abuse"),
                     ("agent_collusion_flag", "Agent collusion")):
        if rcol in frame:
            m = frame[rcol].to_numpy() == 1
            if m.sum():
                rules_vs_model.append({"rule": nm, "rule_hits": int(m.sum()), "caught": int((m & flag).sum()),
                                       "caught_pct": round((m & flag).sum() / m.sum() * 100, 1)})
    if rules_vs_model:
        anyr = np.zeros(n, bool)
        for rcol in meta["rule_columns"]:
            anyr |= frame[rcol].to_numpy() == 1
        model_only, rule_only = int((flag & ~anyr).sum()), int((anyr & ~flag).sum())
        worst = min(rules_vs_model, key=lambda r: r["caught_pct"])
        add("info" if worst["caught_pct"] >= 80 else "medium", "rules",
            "Model and rule-based detection compared",
            f"The model alerts on {pct(np.mean([r['caught_pct'] for r in rules_vs_model]), 0)} of rule hits on average; "
            f"weakest on {worst['rule']} ({pct(worst['caught_pct'], 0)}). It also flagged {n_(model_only)} "
            f"transactions that no rule matched (possible new patterns, or false alarms) while {n_(rule_only)} rule "
            "hits fell below the threshold.",
            [ev_(r["rule"], f"{n_(r['caught'])} of {n_(r['rule_hits'])} caught") for r in rules_vs_model])
        if model_only >= 20:
            rec("r_review", "plan", "Sample-review the model-only alerts",
                f"Have an analyst check about 50 of the {n_(model_only)} alerts no rule matched. Confirmed cases show the "
                "model finds patterns the rules miss; rejected ones guide threshold tuning.", "Evidence for the thesis")

    # 13. data quality
    if meta["warnings"]:
        sev_q = "high" if meta["coverage_pct"] < 40 else "medium"
        rid = None
        if not meta.get("has_devices"):
            rid = rec("r_data", "plan", "Collect device and SIM-change data",
                      "Ask the telco or app team for device identifiers and SIM-change events per account. They are the "
                      "strongest predictors here, and without them alerts are less reliable.",
                      f"Signal coverage now {pct(meta['coverage_pct'], 0)}")
        add(sev_q, "quality", f"Only {pct(meta['coverage_pct'], 0)} of the model's signal was available",
            " ".join(meta["warnings"][:3]),
            [ev_("Signal coverage", pct(meta["coverage_pct"], 0))], [rid] if rid else [])
    if not evaluation:
        rec("r_label", "plan", "Capture confirmed outcomes to measure accuracy",
            "This data has no fraud label, so precision and recall cannot be measured. Record the result of each "
            "investigation (fraud / genuine) and feed it back; those outcomes also let the model be retrained.",
            "Enables measured accuracy")
    # tiered response is always advised
    rec("r_tiers", "plan", "Respond in tiers instead of block-or-allow",
        f"Hold transactions at {hold_lo:.2f}+ ({n_(tiers[0]['count'])}), ask for verification between {t:.2f} and "
        f"{hold_lo:.2f} ({n_(tiers[1]['count'])}), and keep watching the next band ({n_(tiers[2]['count'])}). "
        "This keeps friction for genuine customers low.", "Lower false-alarm friction")

    # drivers insight
    if drivers:
        dtxt = ", ".join(f"{d['label'].lower()} ({d['share']:.0f}%)" for d in drivers[:3])
        add("info", "drivers", "What is driving the alerts", f"Across flagged transactions, the strongest drivers are {dtxt}.",
            [ev_(d["label"], f"{d['share']}% of influence") for d in drivers[:4]])

    order = {"critical": 0, "high": 1, "medium": 2, "info": 3, "good": 4}
    insights.sort(key=lambda i: order[i["severity"]])
    prio = {"now": 0, "soon": 1, "plan": 2}
    recs.sort(key=lambda r: prio[r["priority"]])

    # ---- headline narrative ----
    top_ty = by_type[0] if by_type else None
    parts = [f"Across {window_label or 'the data'}, {n_(n)} transactions worth {money(total_val, cur)} were scored. At a "
             f"threshold of {t:.2f}, {n_(f)} ({pct(fpct)}) are flagged, holding {money(flag_val, cur)}."]
    if top_ty and f:
        parts.append(f"{top_ty['type'].replace('_', ' ').title()} accounts for the most alerts ({n_(top_ty['flagged'])}).")
    if drivers:
        parts.append(f"The main driver is {drivers[0]['label'].lower()}.")
    if critical["count"]:
        parts.append(f"Start with the {n_(critical['count'])} critical alerts ({money(critical['value'], cur)}).")
    if meta["coverage_pct"] < 40:
        parts.append(f"Treat results with care: only {pct(meta['coverage_pct'], 0)} of the model's signal was available.")
    headline = ("Immediate attention needed" if sev in ("critical", "high") or (f and critical["count"] > 0 and fpct >= 5)
                else "Moderate risk" if f else "Low risk")

    return {
        "summary": summary, "tiers": tiers, "by_type": by_type, "by_hour": by_hour, "score_hist": hist,
        "threshold_curve": curve_points(curves, n, bool(has_y)), "evaluation": evaluation,
        "rules_vs_model": rules_vs_model, "top_origins": top_origins, "top_destinations": top_dest,
        "drivers": drivers, "insights": insights, "recommendations": recs,
        "narrative": {"headline": headline, "text": " ".join(parts)},
    }

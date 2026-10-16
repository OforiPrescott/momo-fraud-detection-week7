"""
Project-level overview: the full 6.36M-row dataset summary plus the Week 5/6
model results, with the same automatic interpretation as the live analyses.
Reads the small precomputed files only (see precompute_dashboard_data.py).
"""
import json
import os

from . import scoring
from .insights import money, n_, pct

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
REPORTS = os.path.join(HERE, "..", "reports")

FALLBACK_BASE = {"precision": 0.4941, "recall": 0.9933, "f1": 0.6599, "auc_roc": 0.9935, "auc_pr": 0.9426,
                 "confusion_matrix": {"tn_fp_fn_tp": [1087348, 93370, 613, 91193]}, "n_test": 1272524}
FALLBACK_CMP = {
    "tuned_xgboost_full_train": {"precision": 0.4871, "recall": 0.9955, "f1": 0.6541, "auc_roc": 0.9934, "auc_pr": 0.942},
    "mlp_neural_net": {"precision": 0.9813, "recall": 0.7555, "f1": 0.8537, "auc_roc": 0.9926, "auc_pr": 0.9372},
    "best_config": {"max_depth": 4, "n_estimators": 150, "learning_rate": 0.1},
    "hyperparameter_search_results": [],
}


def _read(path, fallback):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return fallback


def build():
    summary = _read(os.path.join(DATA, "dashboard_summary.json"), None)
    base = _read(os.path.join(REPORTS, "baseline_metrics.json"), FALLBACK_BASE)
    cmp_ = _read(os.path.join(REPORTS, "model_comparison.json"), FALLBACK_CMP)
    imp = sorted(scoring.importances().items(), key=lambda kv: -kv[1])[:10]
    models = [
        {"name": "XGBoost baseline", "week": 5, **{k: base[k] for k in ("precision", "recall", "f1", "auc_roc", "auc_pr")}},
        {"name": "XGBoost tuned", "week": 6, **cmp_["tuned_xgboost_full_train"]},
        {"name": "MLP neural net", "week": 6, **cmp_["mlp_neural_net"]},
    ]
    n_test = base.get("n_test", 1272524)
    tn, fp, fn, tp = base["confusion_matrix"]["tn_fp_fn_tp"]
    P = tp + fn
    for m in models:  # alert workload each model would create on the held-out test set
        tp_m = m["recall"] * P
        m["alerts"] = round(tp_m / m["precision"]) if m["precision"] else 0
        m["alerts_per_1000"] = round(m["alerts"] / n_test * 1000, 1)

    out = {"summary": summary, "models": models, "importance": [{"feature": k, "label": scoring.LABELS.get(k, k),
           "value": round(v, 4)} for k, v in imp], "best_config": cmp_.get("best_config"),
           "search": cmp_.get("hyperparameter_search_results", []), "insights": [], "recommendations": [],
           "narrative": None}
    ins, rec = out["insights"], out["recommendations"]

    def add(sev, id_, title, finding, ev=None, recs=None):
        ins.append({"id": id_, "severity": sev, "title": title, "finding": finding,
                    "evidence": [{"label": a, "value": b} for a, b in (ev or [])], "recs": recs or []})

    def r(id_, prio, title, detail, impact=None):
        rec.append({"id": id_, "priority": prio, "title": title, "detail": detail, "impact": impact}); return id_

    if summary:
        fl = summary["flags"]; total = summary["total_transactions"]
        gap = fl["any_attack_flag"] / max(fl["isFraud"], 1)
        add("high", "coverage", "Financial fraud labels see only a sliver of the risk",
            f"PaySim's own fraud label marks {n_(fl['isFraud'])} transactions ({pct(fl['isFraud'] / total * 100, 2)}). "
            f"Adding the three Ghana-specific patterns raises that to {n_(fl['any_attack_flag'])} "
            f"({pct(summary['any_attack_rate_pct'], 2)}), about {gap:.0f}x more. Monitoring on financial fraud alone would "
            f"miss {pct((1 - fl['isFraud'] / fl['any_attack_flag']) * 100, 0)} of the behaviour this project labels as hostile.",
            [("isFraud", n_(fl["isFraud"])), ("Any attack flag", n_(fl["any_attack_flag"]))],
            [r("o_access", "plan", "Treat access behaviour as a first-class data source",
           "The gap above is the core argument for including access behaviour as a first-class data source: "
           "device, SIM and login events expose threats that transaction amounts alone cannot.", "Evidence")])
        pats = [("PIN-sharing abuse", fl["pin_sharing_flag"]), ("SIM-swap takeover", fl["sim_swap_takeover"]),
                ("Agent collusion", fl["agent_collusion_flag"])]
        big = max(pats, key=lambda p: p[1])
        add("medium", "patterns", f"{big[0]} is the largest pattern",
            f"{big[0]} accounts for {n_(big[1])} transactions ({pct(big[1] / fl['any_attack_flag'] * 100, 0)} of all attack "
            "flags). Patterns can overlap, so the three counts add up to more than the combined total.",
            [(p, n_(v)) for p, v in pats])
        fr, ar = summary["fraud_rate_by_type_pct"], summary["attack_rate_by_type_pct"]
        tf, ta = max(fr, key=fr.get), max(ar, key=ar.get)
        add("medium", "types", f"{ta} has the highest overall attack rate",
            f"{ta} reaches {pct(ar[ta])} attack rate. For PaySim's financial fraud label the highest rate is {tf} at "
            f"{pct(fr[tf], 2)}. Rates, not raw counts, show where an alert is most likely to be real.",
            [(k, f"{pct(v)} attack rate") for k, v in sorted(ar.items(), key=lambda kv: -kv[1])[:4]],
            [r("o_type", "soon", f"Prioritise {ta} monitoring in the next dashboard iteration",
               "Add a per-type view with its own threshold, since one global cut-off hides these differences.")])
    xb, mlp = models[0], models[2]
    extra = xb["alerts"] - mlp["alerts"]
    add("high", "tradeoff", "XGBoost and the neural net make opposite trade-offs",
        f"XGBoost catches {pct(xb['recall'] * 100, 1)} of attacks but only {pct(xb['precision'] * 100, 0)} of its alerts are "
        f"real. The MLP is {pct(mlp['precision'] * 100, 1)} precise but misses {pct((1 - mlp['recall']) * 100, 0)} of attacks. "
        f"On the held-out test set that is about {n_(xb['alerts'])} versus {n_(mlp['alerts'])} alerts, so XGBoost creates "
        f"roughly {n_(extra)} more cases for analysts. Ranking quality (AUC-PR) is nearly identical, so the difference is where "
        "the cut-off sits, a deployment decision.",
        [(m["name"], f"P {m['precision']:.3f} / R {m['recall']:.3f} / {m['alerts_per_1000']} alerts per 1,000")
         for m in models],
        [         r("o_decide", "now", "Determine which error costs more for your use case",
           "A missed attack means lost funds; a false alarm costs analyst time and customer friction. Put a figure "
           "on each and choose the threshold from the dashboard's trade-off curve based on your operational priorities.",
           "Decides which model ships"),
         r("o_tiers", "soon", "Combine both models in tiers",
           "Auto-hold when both models agree on a high score, send XGBoost-only alerts to verification, and let the rest "
           "through. This is an idea to test, not a measured result.", "Fewer false alarms at high recall")])
    if imp:
        top = imp[0]
        add("high", "device", f"{scoring.LABELS.get(top[0], top[0])} is the top predictor",
            f"It carries {pct(top[1] * 100, 0)} of the model's importance, ahead of every amount and balance feature. "
            "This supports the intrusion-data argument, with one caution: the PIN-sharing rule itself is defined from device "
            "counts, so part of this strength reflects how the labels were built. Validating on independently labelled "
            "real data is the stronger proof.",
            [(scoring.LABELS.get(k, k), pct(v * 100, 1)) for k, v in imp[:4]],
            [r("o_real", "plan", "Validate on real, independently labelled data",
               "The upload, database and API options on the Analyze page exist for this. Use real MoMo exports with "
               "investigator-confirmed outcomes to test whether the result holds outside the synthetic labels.",
               "Strengthens confidence")])
    out["recommendations"].sort(key=lambda x: {"now": 0, "soon": 1, "plan": 2}[x["priority"]])
    out["narrative"] = {
        "headline": "Project status: detection pipeline complete, validation on real data next",
        "text": (f"Across {n_(summary['total_transactions']) if summary else 'the'} transactions, the combined attack label "
                 f"covers {pct(summary['any_attack_rate_pct'], 1) if summary else 'a much larger share'} versus "
                 f"{pct(summary['flags']['isFraud'] / summary['total_transactions'] * 100, 2) if summary else '0.13%'} for "
                 "financial fraud alone. Three models were compared on the same held-out set; they rank transactions almost "
                 "equally well and differ in where they set the alert cut-off.") if summary else
        "Run backend/precompute_dashboard_data.py to generate the dataset summary.",
    }
    return out

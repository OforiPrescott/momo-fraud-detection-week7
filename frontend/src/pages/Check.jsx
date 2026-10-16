import { useEffect, useState } from "react";
import { post } from "../api";
import { WhyList, Card } from "../components/ui";
import { pct, riskColor } from "../format";

const BASE = { type: "PAYMENT", amount: 4500, oldbalanceOrg: 30000, newbalanceOrig: 25500, oldbalanceDest: 0, newbalanceDest: 0, hour_of_day: 14, orig_txn_count_so_far: 12, orig_avg_amount_so_far: 4200, orig_distinct_devices: 1, orig_ever_sim_change: 0, dest_distinct_senders: 0 };
const PRESETS = [
  ["Everyday payment", BASE],
  ["SIM-swap drain", { type: "CASH_OUT", amount: 480000, oldbalanceOrg: 480000, newbalanceOrig: 0, oldbalanceDest: 20000, newbalanceDest: 500000, hour_of_day: 2, orig_txn_count_so_far: 6, orig_avg_amount_so_far: 9000, orig_distinct_devices: 2, orig_ever_sim_change: 1, dest_distinct_senders: 3 }],
  ["Two devices, first transaction", { type: "CASH_OUT", amount: 17130, oldbalanceOrg: 0, newbalanceOrig: 0, oldbalanceDest: 836055, newbalanceDest: 853185, hour_of_day: 15, orig_txn_count_so_far: 0, orig_avg_amount_so_far: 17130, orig_distinct_devices: 2, orig_ever_sim_change: 0, dest_distinct_senders: 10 }],
  ["Paying a busy agent", { type: "CASH_OUT", amount: 185000, oldbalanceOrg: 400000, newbalanceOrig: 215000, oldbalanceDest: 900000, newbalanceDest: 1085000, hour_of_day: 11, orig_txn_count_so_far: 3, orig_avg_amount_so_far: 170000, orig_distinct_devices: 1, orig_ever_sim_change: 0, dest_distinct_senders: 34 }],
];
const FIELDS = [
  ["amount", "Amount"], ["oldbalanceOrg", "Sender balance before"], ["newbalanceOrig", "Sender balance after"],
  ["oldbalanceDest", "Receiver balance before"], ["newbalanceDest", "Receiver balance after"], ["hour_of_day", "Hour of day (0 to 23)"],
  ["orig_txn_count_so_far", "Sender's earlier transactions"], ["orig_avg_amount_so_far", "Sender's usual amount"],
  ["orig_distinct_devices", "Devices used by sender"], ["dest_distinct_senders", "Different senders paying the receiver"],
];

export default function Check() {
  const [f, setF] = useState(BASE);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  // Re-scores as you type, so you can watch the risk respond to each change.
  useEffect(() => {
    const t = setTimeout(() => {
      const body = { ...f }; for (const k of Object.keys(body)) if (k !== "type") body[k] = Number(body[k]) || 0;
      post("/api/score", body).then((r) => { setRes(r); setErr(""); }).catch((e) => setErr(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [f]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const r = res?.risk_score ?? 0;
  const action = r >= 0.9 ? ["Hold and call the customer", "var(--crit)"] : r >= 0.5 ? ["Ask for step-up verification", "var(--high)"] : r >= 0.3 ? ["Allow, keep watching", "var(--med)"] : ["Allow", "var(--low)"];
  return (
    <>
      <header className="pagehead"><div><h1>Check one transaction</h1><p>Enter the details of a single transaction and see its risk score and the reasons behind it. Change a value to see how the score responds.</p></div></header>
      <div className="grid g-main">
        <Card title="Transaction details" right={<div className="row">{PRESETS.map(([n, v]) => <button key={n} className="btn sm" onClick={() => setF(v)}>{n}</button>)}</div>}>
          <div className="fields">
            <label className="f">Type<select value={f.type} onChange={set("type")}>{["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"].map((t) => <option key={t}>{t}</option>)}</select></label>
            {FIELDS.map(([k, l]) => <label className="f" key={k}>{l}<input type="number" value={f[k]} onChange={set(k)} /></label>)}
            <label className="f">SIM change on record<select value={f.orig_ever_sim_change} onChange={set("orig_ever_sim_change")}><option value={0}>No</option><option value={1}>Yes</option></select></label>
          </div>
        </Card>
        <Card title="Result">
          {err && <div className="err">{err}</div>}
          {res && (
            <div className="stack">
              <div className="gauge"><div className="big num" style={{ color: riskColor(r) }}>{pct(r * 100, 1)}</div><div><div className="faint" style={{ fontSize: 12.5 }}>Risk score</div><span className="act" style={{ background: action[1] }}>{action[0]}</span></div></div>
              <div className="gaugebar" aria-hidden="true"><i style={{ left: `${r * 100}%` }} /></div>
              <div><h3 style={{ fontSize: 15, marginBottom: 8 }}>Why</h3><WhyList items={res.reasons} /></div>
              <p className="hint">Scored by the trained XGBoost model. The reasons are each input's measured contribution to this score.</p>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

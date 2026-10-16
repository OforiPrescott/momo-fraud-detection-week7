import { Fragment, useEffect, useState } from "react";
import { get, qs } from "../api";
import { full, int, pct, riskColor, typeName } from "../format";
import { useSettings } from "../settings";
import { Busy, WhyList } from "./ui";

const ACTIONS = { "Hold and call the customer": "var(--crit)", "Ask for step-up verification": "var(--high)", "Allow, keep watching": "var(--med)", Allow: "var(--low)" };
const LABEL = { row_id: "Row", step: "Step (hour)", type: "Type", amount: "Amount", nameOrig: "Sender", nameDest: "Receiver", oldbalanceOrg: "Sender balance before", newbalanceOrig: "Sender balance after", label: "Known attack", sim_swap_takeover: "SIM-swap rule", pin_sharing_flag: "PIN-sharing rule", agent_collusion_flag: "Agent-collusion rule" };

/** Case drill-down. `sid`+`rowId` loads a batch row; `live` shows a streamed alert already carrying its reasons. */
export default function CaseDrawer({ sid, rowId, threshold, live, onClose, onOpen }) {
  const { currency } = useSettings();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    if (live) return;
    setData(null); setErr("");
    get(`/api/analysis/${sid}/case/${rowId}?${qs({ threshold })}`).then(setData).catch((e) => setErr(e.message));
  }, [sid, rowId, threshold, live]);

  const risk = live ? live.risk : data?.risk;
  const action = live ? (live.risk >= Math.max(threshold, 0.9) ? "Hold and call the customer" : "Ask for step-up verification") : data?.action;
  const rows = live
    ? [["Type", typeName(live.type)], ["Amount", full(live.amount, currency)], ["Sender", live.orig ?? "n/a"], ["Receiver", live.dest ?? "n/a"], ["Received", new Date(live.ts).toLocaleTimeString([], { hour12: false })], ...(live.actual != null ? [["Known attack (replay)", live.actual ? "Yes" : "No"]] : [])]
    : data ? Object.entries(data.transaction).filter(([k]) => LABEL[k]).map(([k, v]) => [LABEL[k], k === "type" ? typeName(v) : typeof v === "number" && ["amount", "oldbalanceOrg", "newbalanceOrig"].includes(k) ? full(v, currency) : k === "label" || k.endsWith("flag") || k === "sim_swap_takeover" ? (v ? "Yes" : "No") : String(v)]) : [];

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Transaction detail">
        <div className="row">
          <h2>Transaction detail</h2><span className="spacer" />
          <button className="btn sm" onClick={onClose}>Close</button>
        </div>
        {err && <div className="err">{err}</div>}
        {!live && !data && !err && <Busy text="Loading the explanation..." />}
        {risk != null && (
          <>
            <div className="gauge">
              <div className="big num" style={{ color: riskColor(risk) }}>{pct(risk * 100, 1)}</div>
              <div><div className="faint" style={{ fontSize: 12.5 }}>Risk score</div><span className="act" style={{ background: ACTIONS[action] }}>{action}</span></div>
            </div>
            <dl className="kv">{rows.map(([k, v]) => (<Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>))}</dl>
            <div>
              <h3 style={{ fontSize: 15, marginBottom: 8 }}>Why the model scored it this way</h3>
              <WhyList items={live ? live.why : data.why} />
            </div>
            {data?.related?.map((r) => (
              <div key={r.relation} className="note">
                <b>{r.relation}:</b> {int(r.count)} worth {full(r.value, currency)}.
                {onOpen && <div className="chips" style={{ marginTop: 6 }}>{r.examples.map((e) => (<button key={e.row_id} className="btn sm" onClick={() => onOpen(e.row_id)}>{typeName(e.type)} {full(e.amount, currency)}</button>))}</div>}
              </div>
            ))}
            {data && (
              <details>
                <summary style={{ cursor: "pointer", fontWeight: 600 }}>Model inputs and where each came from</summary>
                <table style={{ marginTop: 8 }}><tbody>
                  {Object.entries(data.features).filter(([k]) => !k.startsWith("type_") || data.features[k] === 1).map(([k, v]) => (
                    <tr key={k}><td>{k}</td><td className="r num">{Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 })}</td><td><span className={`badge ${data.source[k]}`}>{data.source[k]}</span></td></tr>
                  ))}
                </tbody></table>
              </details>
            )}
          </>
        )}
      </aside>
    </>
  );
}

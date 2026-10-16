import { pct } from "../format";
import { Card } from "./ui";

const LEGEND = { provided: "Found in your data", derived: "Calculated from your data", default: "Not available, filled with a neutral value" };

export default function DataQuality({ dq }) {
  return (
    <div className="stack">
      <Card title="How much of the model's signal your data provided" sub="Each model input is weighted by how much the trained model relies on it.">
        <div className="row" style={{ alignItems: "baseline" }}>
          <div style={{ fontFamily: "var(--serif)", fontSize: 34, fontWeight: 600 }} className="num">{pct(dq.coverage_pct, 0)}</div>
          <div className="muted">signal coverage</div>
        </div>
        <div className="dq-bar"><i style={{ width: `${dq.coverage_pct}%`, background: dq.coverage_pct < 40 ? "var(--high)" : "var(--low)" }} /></div>
        {dq.warnings.map((w, i) => <div key={i} className="warn" style={{ marginTop: 8 }}>{w}</div>)}
        {dq.notes.map((w, i) => <div key={i} className="note" style={{ marginTop: 8 }}>{w}</div>)}
        {dq.label_name ? <p className="hint" style={{ marginTop: 10 }}>Accuracy was measured against the <b>{dq.label_name}</b> column.</p> : <p className="hint" style={{ marginTop: 10 }}>No confirmed-fraud column was found, so accuracy is not measured.</p>}
      </Card>
      <Card title="Model inputs">
        <div className="tablewrap"><table>
          <thead><tr><th>Input</th><th>Source in your data</th><th className="r">Model reliance</th></tr></thead>
          <tbody>{dq.features.map((f) => (
            <tr key={f.feature}><td>{f.label}</td><td><span className={`badge ${f.source}`}>{LEGEND[f.source]}</span></td><td className="r num">{pct(f.importance * 100, 1)}</td></tr>
          ))}</tbody>
        </table></div>
      </Card>
    </div>
  );
}

import { pct } from "../format";
import { Card } from "./ui";

const DRIFT = { stable: "Similar", moderate: "Somewhat different", major: "Very different" };
const fmt = (v) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : +v.toFixed(2));
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
      {dq.drift?.available && (
        <Card title="How similar is your data to the training data?" sub="Population Stability Index (PSI) per input: under 0.10 similar, 0.10 to 0.25 somewhat different, over 0.25 very different.">
          <div className={dq.drift.overall === "stable" ? "note" : "warn"} style={{ marginBottom: 12 }}>{dq.drift.summary}</div>
          <div className="tablewrap"><table>
            <thead><tr><th>Input</th><th className="r">Typical in training</th><th className="r">Typical in your data</th><th className="r">PSI</th><th>Verdict</th></tr></thead>
            <tbody>{dq.drift.features.map((f) => (
              <tr key={f.feature}><td>{f.label}</td><td className="r num">{fmt(f.reference_median)}</td><td className="r num">{fmt(f.your_median)}</td>
                <td className="r num">{f.psi.toFixed(2)}</td><td><span className={`badge drift-${f.level}`}>{DRIFT[f.level]}</span></td></tr>
            ))}</tbody>
          </table></div>
          <p className="hint" style={{ marginTop: 10 }}>"Typical" is the median. When new data drifts far from the training data, the model's measured accuracy may no longer hold, so validate or retrain before relying on it.</p>
        </Card>
      )}
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

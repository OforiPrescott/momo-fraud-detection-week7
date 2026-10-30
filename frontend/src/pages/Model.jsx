import { useEffect, useState } from "react";
import { get } from "../api";
import { HBars, ModelBars } from "../components/Charts";
import { Busy, Card, Findings, Recommendations } from "../components/ui";
import { int, pct } from "../format";

export default function Model() {
  const [o, setO] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { get("/api/overview").then(setO).catch((e) => setErr(e.message)); }, []);
  if (err) return <div className="err">{err}</div>;
  if (!o) return <Busy text="Loading model results..." />;
  return (
    <>
      <header className="pagehead"><div><h1>Model results</h1><p>Three models compared on the same held-out test set of {int(o.n_test)} transactions they never saw during training.</p></div></header>
      <div className="stack">
        <div className="grid g2">
          <Card title="Precision, recall and balance (F1)" sub="Precision: how many alerts are real. Recall: how many attacks are caught."><ModelBars models={o.models} /></Card>
          <Card title="What drives the model" sub="Share of the XGBoost model's decisions explained by each input."><HBars data={o.importance.map((i) => ({ label: i.label, value: +(i.value * 100).toFixed(1) }))} /></Card>
        </div>
        <Card title="Workload each model would create" sub="Alerts an analyst team would receive on the held-out test set.">
          <div className="tablewrap"><table>
            <thead><tr><th>Model</th><th className="r">Precision</th><th className="r">Recall</th><th className="r">F1</th><th className="r">AUC-PR</th><th className="r">Alerts</th><th className="r">Alerts per 1,000</th></tr></thead>
            <tbody>{o.models.map((m) => <tr key={m.name}><td><b>{m.name}</b></td><td className="r num">{m.precision.toFixed(3)}</td><td className="r num">{m.recall.toFixed(3)}</td><td className="r num">{m.f1.toFixed(3)}</td><td className="r num">{m.auc_pr.toFixed(3)}</td><td className="r num">{int(m.alerts)}</td><td className="r num">{m.alerts_per_1000}</td></tr>)}</tbody>
          </table></div>
        </Card>
        {o.search.length > 0 && <Card title="Hyperparameter search" sub={`Winning setting: depth ${o.best_config.max_depth}, ${o.best_config.n_estimators} trees, learning rate ${o.best_config.learning_rate}. More depth and trees did not improve ranking quality.`}>
          <div className="tablewrap"><table><thead><tr><th className="r">Depth</th><th className="r">Trees</th><th className="r">Learning rate</th><th className="r">AUC-PR</th><th className="r">F1</th></tr></thead>
            <tbody>{o.search.map((s, i) => <tr key={i}><td className="r num">{s.max_depth}</td><td className="r num">{s.n_estimators}</td><td className="r num">{s.learning_rate}</td><td className="r num">{s.auc_pr.toFixed(4)}</td><td className="r num">{s.f1.toFixed(4)}</td></tr>)}</tbody></table></div>
        </Card>}
        <div className="grid g-main">
          <Card title="What the results mean" className="fullwidth"><Findings items={o.insights.filter((i) => ["tradeoff", "device"].includes(i.id))} /></Card>
        </div>
        <p className="foot-note">Labels come from the project's rule-based attack patterns on the access layer, so these figures describe how well the model reproduces that labelling. The Analyse page lets you test it on real, independently labelled data to validate performance in production settings.</p>
      </div>
    </>
  );
}

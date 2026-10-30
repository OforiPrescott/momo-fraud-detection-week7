import { useEffect, useRef, useState } from "react";
import { get, qs } from "../api";
import { ByHourChart, ByTypeChart, ScoreHistogram, TradeoffChart } from "../components/Charts";
import CaseDrawer from "../components/CaseDrawer";
import DataQuality from "../components/DataQuality";
import Explainer from "../components/Explainer";
import FlaggedTable from "../components/FlaggedTable";
import SourcePanel from "../components/SourcePanel";
import { Briefing, Card, Findings, Kpi, Kpis, Recommendations, Tabs } from "../components/ui";
import { full, int, money, pct, typeName } from "../format";
import { useSettings } from "../settings";

export default function Analyze({ result, setResult, goLive }) {
  const { currency } = useSettings();
  const [busy, setBusy] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState("");
  const [threshold, setThreshold] = useState(0.5);
  const [tab, setTab] = useState("summary");
  const [open, setOpen] = useState(null);
  const applied = useRef("");

  const accept = (r) => { applied.current = `${r.analysis_id}|${r.summary.threshold}|${currency}`; setResult(r); setTab("summary"); };

  // Moving the threshold (or currency) re-interprets the data instantly; nothing is re-uploaded.
  useEffect(() => {
    if (!result) return;
    const key = `${result.analysis_id}|${threshold}|${currency}`;
    if (key === applied.current) return;
    const t = setTimeout(() => {
      setUpdating(true);
      get(`/api/analysis/${result.analysis_id}?${qs({ threshold, currency })}`)
        .then((r) => { applied.current = key; setResult(r); })
        .catch((e) => setError(e.message)).finally(() => setUpdating(false));
    }, 250);
    return () => clearTimeout(t);
  }, [threshold, currency, result?.analysis_id]);

  const s = result?.summary, ev = result?.evaluation;
  return (
    <>
      <header className="pagehead">
        <div>
          <h1>Analyse transactions</h1>
          <p>Bring in real data from a file, a database or an API. The dashboard scores every transaction, explains what it found and recommends what to do.</p>
        </div>
        {result && <div className="row"><button className="btn" onClick={() => window.print()}>Print or save as PDF</button><button className="btn" onClick={() => setResult(null)}>Analyse different data</button></div>}
      </header>

      {!result && <SourcePanel busy={busy} error={error} onBusy={setBusy} onError={setError} onResult={accept} threshold={threshold} currency={currency} />}

      {result && (
        <div className="stack" style={{ opacity: updating ? 0.7 : 1, transition: "opacity .15s" }}>
          <div className="row hint">
            <b style={{ color: "var(--ink)" }}>{result.source.name}</b><span>{result.source.detail}</span>
            {result.took_seconds != null && <span>analysed in {result.took_seconds}s</span>}
            <span className="spacer" />
            <button className="btn sm" onClick={goLive}>Replay this data live</button>
          </div>

          <Card title="Alert threshold" sub="Transactions scoring at or above this are flagged. Lower catches more attacks and creates more alerts; higher is stricter.">
            <div className="row" style={{ gap: 18 }}>
              <div style={{ flex: "1 1 320px" }}>
                <input type="range" min="0.05" max="0.99" step="0.01" value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} aria-label="Alert threshold" />
              </div>
              <div style={{ fontFamily: "var(--serif)", fontSize: 26, fontWeight: 600, minWidth: 56 }} className="num">{threshold.toFixed(2)}</div>
              {ev?.suggested && (
                <div className="row">
                  {[["best_f1", "Best balance"], ["recall_95", "Catch 95% of attacks"], ["precision_90", "90% of alerts real"]].filter(([k]) => ev.suggested[k]).map(([k, l]) => (
                    <button key={k} className="btn sm" onClick={() => setThreshold(ev.suggested[k].t)} title={`Precision ${pct(ev.suggested[k].precision * 100, 0)}, recall ${pct(ev.suggested[k].recall * 100, 0)}`}>{l} ({ev.suggested[k].t.toFixed(2)})</button>
                  ))}
                </div>
              )}
            </div>
          </Card>

          <Tabs value={tab} onChange={setTab} tabs={[["summary", "Findings and actions"], ["charts", "Charts"], ["cases", "Cases"], ["quality", "Data quality"]]} />

          {tab === "summary" && (
            <div className="stack">
              <Briefing narrative={result.narrative} tiers={result.tiers} cur={currency} />
              <Kpis>
                <Kpi value={int(s.flagged)} label="Flagged transactions" note={`${pct(s.flagged_pct)} of ${int(s.rows)}`} tone={s.flagged_pct > 12 ? "crit" : s.flagged_pct > 5 ? "high" : ""} />
                <Kpi value={money(s.flagged_value, currency)} label="Value flagged" note={`${pct(s.flagged_value_pct)} of ${money(s.total_value, currency)}`} />
                <Kpi value={int(s.critical)} label="Critical alerts" note={money(s.critical_value, currency)} tone={s.critical ? "crit" : "ok"} />
                {ev ? <>
                  <Kpi value={pct(ev.recall * 100, 1)} label="Attacks caught" note={`${int(ev.tp)} of ${int(ev.positives)}`} />
                  <Kpi value={pct(ev.precision * 100, 1)} label="Alerts that are real" note={`${int(ev.fp)} false alarms`} />
                </> : <Kpi value={s.mean_risk.toFixed(3)} label="Average risk score" note="No labels to measure accuracy" />}
              </Kpis>
                <div className="grid g-main">
                  <Card title="Key insights" className="fullwidth"><Findings items={result.insights} /></Card>
                  <Explainer s={s} ev={ev} dq={result.data_quality} threshold={threshold} cur={currency} />
                </div>
            </div>
          )}

          {tab === "charts" && (
            <div className="grid g2">
              <Card title="Share flagged, by transaction type"><ByTypeChart data={result.by_type} /></Card>
              {result.by_hour.length > 0 ? <Card title="Share flagged, by hour of day" sub="Red bars are the late-night window, 00:00 to 04:59."><ByHourChart data={result.by_hour} /></Card>
                : <Card title="Share flagged, by hour of day"><p className="muted">This data has no time information, so hourly patterns cannot be shown.</p></Card>}
              <Card title="How risk scores are spread" sub="Most genuine transactions sit near zero. The dashed line is your threshold."><ScoreHistogram data={result.score_hist} threshold={threshold} /></Card>
              <Card title={ev ? "Precision and recall as the threshold moves" : "Alerts as the threshold moves"} sub={ev ? "Pick the threshold where the cost of a missed attack and a false alarm balance for your team." : "Add a confirmed-fraud column to see precision and recall."}><TradeoffChart data={result.threshold_curve} threshold={threshold} /></Card>
              {result.drivers.length > 0 && <Card title="What drives the alerts" sub="Average influence on flagged transactions."><div className="stack" style={{ gap: 8 }}>{result.drivers.map((d) => (
                <div key={d.feature} className="row"><span style={{ width: 190 }}>{d.label}</span><div style={{ flex: 1, height: 10, background: "var(--surface-3)", borderRadius: 5 }}><div style={{ width: `${d.share}%`, height: "100%", background: "var(--blue)", borderRadius: 5 }} /></div><b className="num" style={{ width: 52, textAlign: "right" }}>{pct(d.share, 0)}</b></div>))}</div></Card>}
              {result.rules_vs_model.length > 0 && <Card title="Rule-based detection versus the model" sub="Share of each rule's hits that the model also flags at this threshold."><div className="stack" style={{ gap: 10 }}>{result.rules_vs_model.map((r) => (
                <div key={r.rule}><div className="row"><span>{r.rule}</span><span className="spacer" /><b className="num">{pct(r.caught_pct, 0)}</b><span className="hint num">{int(r.caught)} of {int(r.rule_hits)}</span></div><div style={{ height: 8, background: "var(--surface-3)", borderRadius: 4 }}><div style={{ width: `${r.caught_pct}%`, height: "100%", background: "var(--low)", borderRadius: 4 }} /></div></div>))}</div></Card>}
            </div>
          )}

          {tab === "cases" && (
            <div className="stack">
              {(result.top_origins.length > 0 || result.top_destinations.length > 0) && (
                <div className="grid g2">
                  {result.top_origins.length > 0 && <Card title="Senders flagged more than once" sub="Strongest account-takeover candidates."><div className="tablewrap"><table><thead><tr><th>Sender</th><th className="r">Alerts</th><th className="r">Value</th></tr></thead><tbody>{result.top_origins.map((o) => <tr key={o.account}><td>{o.account}</td><td className="r num">{o.flagged}</td><td className="r num">{money(o.value, currency)}</td></tr>)}</tbody></table></div></Card>}
                  {result.top_destinations.length > 0 && <Card title="Receivers collecting flagged payments" sub="Possible agent collusion or mule accounts."><div className="tablewrap"><table><thead><tr><th>Receiver</th><th className="r">Alerts</th><th className="r">Senders</th><th className="r">Value</th></tr></thead><tbody>{result.top_destinations.map((o) => <tr key={o.account}><td>{o.account}</td><td className="r num">{o.flagged}</td><td className="r num">{o.senders}</td><td className="r num">{money(o.value, currency)}</td></tr>)}</tbody></table></div></Card>}
                </div>
              )}
              <Card title="Flagged transactions" sub="Select a row to see exactly why it was flagged."><FlaggedTable sid={result.analysis_id} threshold={threshold} types={result.by_type.map((t) => t.type)} onOpen={setOpen} /></Card>
            </div>
          )}

          {tab === "quality" && <DataQuality dq={result.data_quality} />}
        </div>
      )}
      {open != null && <CaseDrawer sid={result.analysis_id} rowId={open} threshold={threshold} onClose={() => setOpen(null)} onOpen={setOpen} />}
    </>
  );
}

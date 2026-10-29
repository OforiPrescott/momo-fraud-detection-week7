import { useState } from "react";
import { API } from "../api";
import { ByTypeChart } from "../components/Charts";
import CaseDrawer from "../components/CaseDrawer";
import { Briefing, Card, Empty, Findings, Kpi, Kpis, Recommendations } from "../components/ui";
import { full, int, pct, riskColor, timeOf, typeName } from "../format";
import { useLive } from "../live";
import { useSettings } from "../settings";

export default function Live({ analysisResult, goAccount }) {
  const L = useLive();
  const { currency } = useSettings();
  const [rate, setRate] = useState(10);
  const [source, setSource] = useState("sample");
  const [open, setOpen] = useState(null);
  const [err, setErr] = useState("");
  const A = L.analysis;
  const base = API || window.location.origin;
  const sample = `curl -X POST ${base}/api/ingest \\\n  -H "Content-Type: application/json" \\\n  -H "X-API-Key: YOUR_API_KEY" \\\n  -d '{"type":"CASH_OUT","amount":250000,"nameOrig":"C1001","nameDest":"C2002",\n       "device_id":"dev-77","sim_change":1,"oldbalanceOrg":250000,"newbalanceOrig":0}'`;
  const guard = (p) => p.catch((e) => setErr(e.message));

  return (
    <>
      <header className="pagehead">
        <div>
          <h1>Live monitor</h1>
          <p>Transactions are scored the moment they arrive. Each one updates the feed, the counters and the interpretation below.</p>
        </div>
        <div className="row"><span className={`dot ${L.connected ? "ok" : "bad"}`} /><span className="muted">{L.connected ? "Stream connected" : "Stream disconnected, retrying"}</span></div>
      </header>
      {err && <div className="err" style={{ marginBottom: 12 }} role="alert">{err}</div>}

      <div className="stack">
        <Card title="Feed controls" sub="Replay a dataset to rehearse, or point your own system at the ingest endpoint for live traffic.">
          <div className="row" style={{ gap: 18, alignItems: "flex-end", flexWrap: "wrap" }}>
            <label className="f" style={{ width: 230 }}>Replay source
              <select value={source} onChange={(e) => setSource(e.target.value)} disabled={L.replay.running}>
                <option value="sample">Project sample (5,000)</option>
                {analysisResult && <option value={analysisResult.analysis_id}>{analysisResult.source.name}</option>}
              </select>
            </label>
            <label className="f" style={{ width: 200 }}>Speed: <b className="num">{rate} per second</b>
              <input type="range" min="1" max="100" value={rate} onChange={(e) => { setRate(+e.target.value); L.replay.running && L.setRate(+e.target.value); }} />
            </label>
            <label className="f" style={{ width: 220 }}>Alert threshold: <b className="num">{L.threshold.toFixed(2)}</b>
              <input type="range" min="0.05" max="0.99" step="0.01" value={L.threshold} onChange={(e) => L.setThreshold(+e.target.value)} />
            </label>
            <span className="spacer" />
            {L.replay.running ? <button className="btn danger" onClick={() => guard(L.stopReplay())}>Stop replay</button>
              : <button className="btn primary" onClick={() => { setErr(""); guard(L.startReplay(source, rate)); }}>Start replay</button>}
            <button className="btn" onClick={() => guard(L.reset())}>Clear</button>
          </div>
          <details style={{ marginTop: 14 }}>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>Connect your own system</summary>
            <div className="stack" style={{ marginTop: 10 }}>
              <p className="hint">Have the mobile money platform (or a webhook) send each transaction to the endpoint below. Field names such as amount, type, nameOrig, nameDest, device_id and sim_change are recognised, and a list of transactions can be sent in one request. Transactions sent with your personal API key appear only on your own monitor. <button className="link" onClick={goAccount}>Create an API key on your Account page.</button></p>
              <pre className="code">{sample}</pre>
            </div>
          </details>
        </Card>

        <Kpis>
          <Kpi value={int(L.totals.total)} label="Transactions scored" note={L.replay.running ? `Replaying ${L.replay.source}` : "Waiting for transactions"} />
          <Kpi value={int(L.totals.flagged)} label="Flagged" note={L.totals.total ? `${pct((L.totals.flagged / L.totals.total) * 100)} of all` : ""} tone={L.totals.flagged ? "crit" : ""} />
          <Kpi value={A?.live ? A.live.rate_per_sec : "0"} label="Per second (last 10s)" />
          <Kpi value={A?.live ? `${A.live.latency_ms} ms` : "n/a"} label="Time to score one" />
        </Kpis>

        <Card title="Pulse" sub="The latest transactions, oldest on the left. Taller and redder means riskier.">
          <div className="pulse" aria-hidden="true">
            {L.pulse.map((r, i) => <i key={i} style={{ height: `${Math.max(6, r * 100)}%`, background: riskColor(r) }} />)}
          </div>
        </Card>

        <div className="grid g-main">
          <Card title="Incoming transactions" sub="Flagged ones are highlighted. Select one to see why.">
            <div className="feed" role="list">
              {!L.feed.length && <div className="empty-in feed empty" style={{ border: 0 }}>Nothing yet. Start a replay or send a transaction to the ingest endpoint.</div>}
              {L.feed.map((e) => (
                <div key={e.id} role="listitem" className={`it ${e.flagged ? "fl" : ""}`} onClick={() => e.flagged && setOpen(e)} tabIndex={e.flagged ? 0 : -1} onKeyDown={(k) => k.key === "Enter" && e.flagged && setOpen(e)}>
                  <span className="faint num">{timeOf(e.ts)}</span><span>{typeName(e.type)}</span>
                  <span className="a num">{full(e.amount, currency)} <span className="faint">{e.orig ? `from ${e.orig}` : ""}</span></span>
                  <b className="num" style={{ color: riskColor(e.risk), textAlign: "right" }}>{pct(e.risk * 100, 1)}</b>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Flagged by type" sub={A ? `Last ${A.live.window} transactions` : ""}>
            {A ? <ByTypeChart data={A.by_type} /> : <p className="muted">Appears after 20 transactions.</p>}
          </Card>
        </div>

        {A ? (
          <>
            <Briefing narrative={A.narrative} tiers={A.tiers} cur={currency} />
              <div className="grid g-main">
                <Card title="Key insights" className="fullwidth"><Findings items={A.insights} /></Card>
              </div>
          </>
        ) : <Empty title="Interpretation starts after 20 transactions">Once enough transactions have been scored, a plain-language briefing, findings and recommended actions appear here and keep updating.</Empty>}
      </div>
      {open && <CaseDrawer live={open} threshold={L.threshold} onClose={() => setOpen(null)} />}
    </>
  );
}

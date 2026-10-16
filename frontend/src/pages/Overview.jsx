import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "../api";
import { Briefing, Busy, Card, Findings, Kpi, Kpis, Recommendations } from "../components/ui";
import { PALETTE, int, pct, typeName } from "../format";

const ax = { fontSize: 12, fill: "#5b6878" };

export default function Overview({ go }) {
  const [o, setO] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { get("/api/overview").then(setO).catch((e) => setErr(e.message)); }, []);
  if (err) return <div className="err" role="alert">{err} Check that the API is running: <code>uvicorn backend.main:app --port 8000</code></div>;
  if (!o) return <Busy text="Loading the project summary..." />;
  const s = o.summary;
  const types = s ? Object.keys(s.attack_rate_by_type_pct).map((t) => ({ name: typeName(t), attack: s.attack_rate_by_type_pct[t], fraud: s.fraud_rate_by_type_pct[t], count: s.transaction_count_by_type[t] })) : [];
  const pats = s ? [["PIN-sharing abuse", s.flags.pin_sharing_flag], ["SIM-swap takeover", s.flags.sim_swap_takeover], ["Agent collusion", s.flags.agent_collusion_flag], ["PaySim isFraud", s.flags.isFraud]].map(([name, v]) => ({ name, v })) : [];
  return (
    <>
      <header className="pagehead">
        <div><h1>Mobile money fraud and intrusion detection</h1><p>A machine learning system for detecting fraud and intrusion attempts in mobile money platforms, built on transaction data with device and SIM access patterns.</p></div>
        <div className="row"><button className="btn primary" onClick={() => go("analyze")}>Analyse your data</button><button className="btn" onClick={() => go("live")}>Open the live monitor</button></div>
      </header>
      <div className="stack">
        <Briefing narrative={o.narrative} />
        {s && <Kpis>
          <Kpi value={int(s.total_transactions)} label="Transactions" note="Real PaySim data" />
          <Kpi value={int(s.flags.isFraud)} label="PaySim financial fraud" note={pct((s.flags.isFraud / s.total_transactions) * 100, 2)} />
          <Kpi value={int(s.flags.any_attack_flag)} label="Any attack pattern" note={pct(s.any_attack_rate_pct, 1)} tone="crit" />
          <Kpi value={int(s.flags.pin_sharing_flag)} label="PIN-sharing abuse" tone="high" />
          <Kpi value={int(s.flags.sim_swap_takeover)} label="SIM-swap takeover" tone="high" />
          <Kpi value={int(s.flags.agent_collusion_flag)} label="Agent collusion" tone="high" />
        </Kpis>}
        {s && <div className="grid g2">
          <Card title="Attack rate by transaction type" sub="Share of each type carrying any attack label."><ResponsiveContainer width="100%" height={240}><BarChart data={types} margin={{ left: -8 }}><CartesianGrid stroke="#e6ebf1" vertical={false} /><XAxis dataKey="name" tick={ax} /><YAxis tick={ax} unit="%" /><Tooltip formatter={(v) => `${v}%`} /><Bar isAnimationActive={false} dataKey="attack" name="Any attack" fill={PALETTE.blue} radius={[3, 3, 0, 0]} /><Bar isAnimationActive={false} dataKey="fraud" name="PaySim isFraud" fill={PALETTE.crit} radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></Card>
          <Card title="Flagged transactions by pattern" sub="Patterns overlap, so counts add up to more than the combined total."><ResponsiveContainer width="100%" height={240}><BarChart data={pats} layout="vertical" margin={{ left: 12, right: 20 }}><CartesianGrid stroke="#e6ebf1" horizontal={false} /><XAxis type="number" tick={ax} tickFormatter={(v) => `${Math.round(v / 1000)}K`} /><YAxis type="category" dataKey="name" tick={ax} width={130} /><Tooltip formatter={(v) => int(v)} /><Bar isAnimationActive={false} dataKey="v" name="Transactions" fill={PALETTE.navy} radius={[0, 3, 3, 0]} /></BarChart></ResponsiveContainer></Card>
        </div>}
        <div className="grid g-main">
          <Card title="Key insights" className="fullwidth"><Findings items={o.insights} /></Card>
        </div>
      </div>
    </>
  );
}

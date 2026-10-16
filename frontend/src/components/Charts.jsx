import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PALETTE, int, typeName } from "../format";

const axis = { fontSize: 12, fill: "#5b6878" };
const grid = <CartesianGrid stroke="#e6ebf1" vertical={false} />;
const tip = { contentStyle: { borderRadius: 6, border: "1px solid #d9dfe7", fontSize: 12.5 } };
const H = 250;

export const ByTypeChart = ({ data }) => (
  <ResponsiveContainer width="100%" height={H}>
    <BarChart data={data.map((d) => ({ ...d, name: typeName(d.type) }))} margin={{ left: -8, right: 8 }}>
      {grid}<XAxis dataKey="name" tick={axis} /><YAxis tick={axis} unit="%" />
      <Tooltip {...tip} formatter={(v, n, p) => [`${v}% (${int(p.payload.flagged)} of ${int(p.payload.count)})`, "Flagged"]} />
      <Bar isAnimationActive={false} dataKey="flagged_pct" fill={PALETTE.blue} radius={[3, 3, 0, 0]} />
    </BarChart>
  </ResponsiveContainer>
);

export const ByHourChart = ({ data }) => (
  <ResponsiveContainer width="100%" height={H}>
    <BarChart data={data} margin={{ left: -8, right: 8 }}>
      {grid}<XAxis dataKey="hour" tick={axis} interval={1} /><YAxis tick={axis} unit="%" />
      <Tooltip {...tip} labelFormatter={(h) => `${String(h).padStart(2, "0")}:00`} formatter={(v, n, p) => [`${v}% (${int(p.payload.flagged)} of ${int(p.payload.count)})`, "Flagged"]} />
      <Bar isAnimationActive={false} dataKey="flagged_pct" radius={[3, 3, 0, 0]}>
        {data.map((d) => <Cell key={d.hour} fill={d.hour < 5 ? PALETTE.crit : PALETTE.blue} />)}
      </Bar>
    </BarChart>
  </ResponsiveContainer>
);

export const ScoreHistogram = ({ data, threshold }) => {
  const labelled = data[0]?.attacks !== undefined;
  return (
    <ResponsiveContainer width="100%" height={H}>
      <BarChart data={data} margin={{ left: -8, right: 8 }} barCategoryGap={1}>
        {grid}<XAxis dataKey="bin" tick={axis} interval={3} /><YAxis tick={axis} scale="sqrt" tickFormatter={int} />
        <Tooltip {...tip} labelFormatter={(b) => `Risk ${b} and above`} />
        {labelled ? (<>
          <Bar isAnimationActive={false} dataKey="normal" stackId="a" name="Not an attack" fill={PALETTE.grey} />
          <Bar isAnimationActive={false} dataKey="attacks" stackId="a" name="Known attack" fill={PALETTE.crit} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </>) : <Bar isAnimationActive={false} dataKey="count" name="Transactions" fill={PALETTE.blue} />}
        <ReferenceLine x={(Math.floor(threshold * 20) / 20).toFixed(2)} stroke={PALETTE.navy} strokeDasharray="4 3" />
      </BarChart>
    </ResponsiveContainer>
  );
};

/** Threshold trade-off: moving right means fewer alerts but more missed attacks. */
export const TradeoffChart = ({ data, threshold }) => {
  const hasP = data[0]?.precision !== undefined;
  return (
    <ResponsiveContainer width="100%" height={H + 20}>
      <ComposedChart data={data} margin={{ left: -8, right: 8 }}>
        {grid}
        <XAxis dataKey="t" tick={axis} type="number" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} />
        <YAxis tick={axis} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
        <Tooltip {...tip} labelFormatter={(t) => `Threshold ${t}`} formatter={(v, n) => [`${(v * 100).toFixed(1)}%`, n]} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {hasP ? (<>
          <Line isAnimationActive={false} dataKey="precision" name="Precision (alerts that are real)" stroke={PALETTE.blue} dot={false} strokeWidth={2} />
          <Line isAnimationActive={false} dataKey="recall" name="Recall (attacks caught)" stroke={PALETTE.crit} dot={false} strokeWidth={2} />
          <Line isAnimationActive={false} dataKey="f1" name="Balance (F1)" stroke={PALETTE.low} dot={false} strokeDasharray="4 3" />
        </>) : (
          <Line isAnimationActive={false} dataKey={(d) => d.flagged_pct / 100} name="Share of transactions flagged" stroke={PALETTE.blue} dot={false} strokeWidth={2} />
        )}
        <ReferenceLine x={threshold} stroke={PALETTE.navy} strokeDasharray="4 3" />
      </ComposedChart>
    </ResponsiveContainer>
  );
};

export const HBars = ({ data, valueKey = "value", unit = "%", color = PALETTE.blue, height }) => (
  <ResponsiveContainer width="100%" height={height || Math.max(120, data.length * 34)}>
    <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24 }}>
      <CartesianGrid stroke="#e6ebf1" horizontal={false} />
      <XAxis type="number" tick={axis} unit={unit} />
      <YAxis type="category" dataKey="label" tick={axis} width={150} />
      <Tooltip {...tip} formatter={(v) => [`${v}${unit}`, ""]} />
      <Bar isAnimationActive={false} dataKey={valueKey} fill={color} radius={[0, 3, 3, 0]} />
    </BarChart>
  </ResponsiveContainer>
);

export const ModelBars = ({ models }) => (
  <ResponsiveContainer width="100%" height={H + 20}>
    <BarChart data={models.map((m) => ({ name: m.name, Precision: m.precision, Recall: m.recall, F1: m.f1 }))} margin={{ left: -8, right: 8 }}>
      {grid}<XAxis dataKey="name" tick={axis} /><YAxis tick={axis} domain={[0, 1]} />
      <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
      <Bar isAnimationActive={false} dataKey="Precision" fill={PALETTE.blue} radius={[3, 3, 0, 0]} />
      <Bar isAnimationActive={false} dataKey="Recall" fill={PALETTE.crit} radius={[3, 3, 0, 0]} />
      <Bar isAnimationActive={false} dataKey="F1" fill={PALETTE.low} radius={[3, 3, 0, 0]} />
    </BarChart>
  </ResponsiveContainer>
);

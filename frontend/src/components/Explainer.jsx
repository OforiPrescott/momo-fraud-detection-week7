// "What these numbers mean": every figure on the results page restated as a plain sentence, using the
// actual values, so someone with no data-science background can read the analysis correctly.
import { int, money, pct } from "../format";
import { Card } from "./ui";

export default function Explainer({ s, ev, dq, threshold, cur }) {
  const t = Math.round(threshold * 100);
  const hold = Math.max(90, t);
  const items = [
    ["Risk score", "0% to 100% per transaction",
      "The model's estimate of how likely each transaction is to be fraud or an account takeover. It is an estimate based on patterns, not proof: use it to decide what to look at first."],
    ["Alert threshold", `${t}%`,
      `Every transaction scoring ${t}% or more is flagged. Here that is ${int(s.flagged)} of ${int(s.rows)} transactions (${pct(s.flagged_pct)}). Lower the threshold to catch more attacks at the cost of more alerts; raise it for fewer, surer alerts.`],
    ["Value flagged", money(s.flagged_value, cur),
      `The flagged transactions move ${money(s.flagged_value, cur)}, which is ${pct(s.flagged_value_pct)} of all the money in this data. This is the amount at risk if every alert were real.`],
    ["Critical alerts", int(s.critical),
      `${int(s.critical)} transactions scored ${hold}% or higher. The model is most certain about these; hold them and confirm with the customer before releasing funds.`],
  ];
  if (ev) {
    const missed = ev.fn ?? Math.max(ev.positives - ev.tp, 0);
    const share = s.flagged ? (ev.fp / s.flagged) * 100 : 0;
    const per100 = ev.fp === 0 ? "none of the alerts" : share < 1 ? "fewer than 1 in every 100 alerts" : `about ${Math.round(share)} in every 100 alerts`;
    const alarms = `${int(ev.fp)} ${ev.fp === 1 ? "was a false alarm" : "were false alarms"}`;
    items.push(
      ["Attacks caught (recall)", pct(ev.recall * 100, 1),
        `Your data marks ${int(ev.positives)} transactions as confirmed attacks. The model flagged ${int(ev.tp)} of them and missed ${int(missed)}. Recall answers "of the real attacks, how many did we catch?"`],
      ["Alerts that are real (precision)", pct(ev.precision * 100, 1),
        `Of the ${int(s.flagged)} alerts, ${int(ev.tp)} were real attacks and ${alarms}: ${per100} would be checked for nothing. Precision answers "when we raise an alert, how often are we right?"`],
    );
  } else {
    items.push(["Accuracy", "Not measured",
      "Your data has no column saying which transactions were confirmed fraud, so the platform cannot tell how many alerts are right or how many attacks were missed. Add one (for example isFraud, 1 or 0) to measure it."]);
  }
  items.push(["Signal coverage", pct(dq.coverage_pct, 0),
    dq.coverage_pct >= 80 ? "Your data supplied nearly everything the model relies on, so the scores use its full strength."
      : dq.coverage_pct >= 40 ? "Your data supplied part of what the model relies on. Scores are useful but weaker; the Data quality tab lists what is missing."
        : "Your data supplied little of what the model relies on (usually device and SIM-change information). Treat scores as a rough first pass; the Data quality tab lists what to add."]);
  if (dq.drift?.available) {
    items.push(["Similarity to training data", { stable: "Similar", moderate: "Somewhat different", major: "Very different" }[dq.drift.overall], dq.drift.summary]);
  }

  return (
    <Card title="What these numbers mean" sub="Each figure above, explained in plain language with your results." className="fullwidth">
      <dl className="explain">
        {items.map(([term, value, text]) => (
          <div key={term}>
            <dt>{term}<b className="num">{value}</b></dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

import { int, pct, money, riskColor } from "../format";

export const Icon = ({ name }) => {
  const p = {
    overview: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
    analyze: "M4 19V9m6 10V5m6 14v-7m4 7H2",
    live: "M2 12h4l3-8 4 16 3-8h6",
    check: "M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6zM8.5 12l2.5 2.5 4.5-5",
    model: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5",
    file: "M6 2h8l5 5v15H6zM14 2v5h5",
    db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    api: "M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
    flask: "M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2.2h12.4a1.5 1.5 0 0 0 1.3-2.2L14 9V3",
    user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5",
    logout: "M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 17l-5-5 5-5M5 12h11",
    eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    eyeOff: "M3 3l18 18M10.6 5.1A10.4 10.4 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3 3.9M6.6 6.6C3.9 8.3 2 12 2 12s3.6 7 10 7c1.8 0 3.4-.5 4.8-1.3M9.9 9.9a3 3 0 0 0 4.2 4.2",
    key: "M14.5 3a6.5 6.5 0 1 1-4.4 11.3L8 16.4V19H5.4v2.6H2.5V18.7l7.2-7.2A6.5 6.5 0 0 1 14.5 3zM16 8.5h.01",
    lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
    bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  }[name];
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={p} />
    </svg>
  );
};

export const Kpi = ({ value, label, note, tone }) => (
  <div className={`kpi ${tone || ""}`}>
    <div className="v num">{value}</div>
    <div className="l">{label}</div>
    {note && <div className="n">{note}</div>}
  </div>
);
export const Kpis = ({ children }) => <div className="kpis">{children}</div>;

export const Card = ({ title, sub, right, children, className = "" }) => (
  <section className={`card ${className}`}>
    {(title || right) && (
      <div className="ch">
        <div>
          <h3>{title}</h3>
          {sub && <div className="sub">{sub}</div>}
        </div>
        {right}
      </div>
    )}
    {children}
  </section>
);

export const Empty = ({ title, children }) => (
  <div className="empty">
    <b>{title}</b>
    <div style={{ maxWidth: 520 }}>{children}</div>
  </div>
);

export const Tabs = ({ tabs, value, onChange }) => (
  <div className="tabs" role="tablist">
    {tabs.map(([k, label]) => (
      <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>
        {label}
      </button>
    ))}
  </div>
);

const SEV_LABEL = { critical: "Critical", high: "High", medium: "Medium", info: "For information", good: "Good news" };
const SEV_COLOR = { critical: "var(--crit)", high: "var(--high)", medium: "var(--med)", info: "var(--blue)", good: "var(--low)" };

/** The headline: plain-language summary the analyst reads first. */
export function Briefing({ narrative, tiers, cur, topSeverity, children }) {
  if (!narrative) return null;
  const sevKey = narrative.headline.startsWith("Immediate") ? "critical" : narrative.headline.startsWith("Moderate") ? "medium" : narrative.headline.startsWith("Project") ? "info" : "good";
  return (
    <div className="briefing" style={{ "--sev": SEV_COLOR[sevKey] }}>
      <div className="bar" />
      <div className="body">
        <h2>{narrative.headline}</h2>
        <p className="t">{narrative.text}</p>
        {tiers && <Ribbon tiers={tiers} cur={cur} />}
        {children}
      </div>
    </div>
  );
}

const TIER_COLOR = { hold: "var(--crit)", verify: "var(--high)", watch: "var(--med)", allow: "#c4ccd6" };
const TIER_DESC = { hold: "Highest risk. Stop and confirm with the account holder before releasing funds.", verify: "Above the alert threshold. Ask for a one-time code or biometric check.", watch: "Close to the threshold. Let through, but keep an eye on the account.", allow: "No action needed." };

/** Risk ribbon: every transaction falls into exactly one response tier. */
export function Ribbon({ tiers, cur }) {
  const total = tiers.reduce((a, t) => a + t.count, 0) || 1;
  return (
    <div>
      <div className="ribbon" role="img" aria-label="Share of transactions in each response tier">
        {tiers.map((t) => {
          const w = (t.count / total) * 100;
          return (
            <div key={t.id} className={t.id} style={{ width: `${Math.max(w, t.count ? 0.8 : 0)}%` }} title={`${t.label}: ${int(t.count)}`}>
              {w > 7 ? `${w.toFixed(w < 10 ? 1 : 0)}%` : ""}
            </div>
          );
        })}
      </div>
      <div className="legend">
        {tiers.map((t) => (
          <div key={t.id}>
            <i style={{ background: TIER_COLOR[t.id] }} />
            <p style={{ margin: 0 }}>
              <b>{t.label}</b>
              <span className="num">{int(t.count)} transactions{t.id !== "allow" ? `, ${money(t.value, cur)}` : ""}</span>
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Findings({ items }) {
  if (!items?.length) return <p className="muted">No findings yet.</p>;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {items.map((i) => (
        <article key={i.id} className={`finding s-${i.severity}`}>
          <h4>
            <span className="sev">{SEV_LABEL[i.severity]}</span>
            {i.title}
          </h4>
          <p>{i.finding}</p>
          {i.evidence?.length > 0 && (
            <div className="chips">
              {i.evidence.map((e, k) => (
                <span className="chip" key={k}>
                  {e.label}: <b className="num">{e.value}</b>
                </span>
              ))}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

const PRIO = { now: ["Do now", "p-now"], soon: ["This week", "p-soon"], plan: ["Plan for", "p-plan"] };
export function Recommendations({ items }) {
  if (!items?.length) return <p className="muted">No recommendations yet.</p>;
  return (
    <div>
      {["now", "soon", "plan"].map((k) => {
        const list = items.filter((r) => r.priority === k);
        if (!list.length) return null;
        return (
          <div className="recgroup" key={k}>
            <h4>
              <span className={`pill ${PRIO[k][1]}`}>{PRIO[k][0]}</span>
            </h4>
            {list.map((r) => (
              <div className="rec" key={r.id}>
                <b>{r.title}</b>
                <p>{r.detail}</p>
                {r.impact && <span className="imp">{r.impact}</span>}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

export const RiskBadge = ({ r }) => (
  <div className="riskcell">
    <div className="riskbar"><i style={{ width: `${r * 100}%`, background: riskColor(r) }} /></div>
    <span className="rv num" style={{ color: riskColor(r) }}>{pct(r * 100, 1)}</span>
  </div>
);

export const Busy = ({ text }) => (
  <div className="stack" style={{ gap: 8 }}>
    <div className="progress" role="progressbar" aria-label={text} />
    <div className="hint">{text}</div>
  </div>
);

/** Signed contribution list ("why this score"): bars grow right (raises risk) or left (lowers risk). */
export function WhyList({ items }) {
  if (!items?.length) return <p className="muted">No strong drivers for this transaction.</p>;
  const max = Math.max(...items.map((i) => Math.abs(i.impact)), 0.5);
  return (
    <div className="why">
      {items.map((i, k) => (
        <div className="w" key={k}>
          <div className="txt">
            <b>{i.text}</b>
            <span>{i.direction === "up" ? "Raises the risk score" : "Lowers the risk score"}</span>
          </div>
          <div className="div" aria-hidden="true">
            <i className={i.direction} style={{ width: `${(Math.abs(i.impact) / max) * 50}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

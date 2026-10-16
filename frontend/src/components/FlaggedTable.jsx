import { useEffect, useState } from "react";
import { API, get, qs } from "../api";
import { full, int, typeName } from "../format";
import { useSettings } from "../settings";
import { RiskBadge } from "./ui";

const PAGE = 15;
const RULES = { sim_swap_takeover: "SIM-swap", pin_sharing_flag: "PIN-sharing", agent_collusion_flag: "Agent collusion" };

/** Server-side filtered, sorted, paginated list of flagged transactions. Click a row for the drill-down. */
export default function FlaggedTable({ sid, threshold, types, onOpen }) {
  const { currency } = useSettings();
  const [f, setF] = useState({ type: "", q: "", sort: "risk", desc: true, page: 0 });
  const [data, setData] = useState({ total: 0, rows: [] });
  const [q, setQ] = useState("");
  useEffect(() => { const t = setTimeout(() => setF((x) => ({ ...x, q, page: 0 })), 300); return () => clearTimeout(t); }, [q]);
  useEffect(() => {
    get(`/api/analysis/${sid}/flagged?${qs({ threshold, type: f.type, q: f.q, sort: f.sort, desc: f.desc, page: f.page, page_size: PAGE })}`).then(setData).catch(() => setData({ total: 0, rows: [] }));
  }, [sid, threshold, f]);
  const sortBy = (k) => setF((x) => ({ ...x, sort: k, desc: x.sort === k ? !x.desc : true, page: 0 }));
  const head = (k, label, cls = "") => (
    <th className={`sortable ${cls}`} onClick={() => sortBy(k)} aria-sort={f.sort === k ? (f.desc ? "descending" : "ascending") : "none"}>
      {label}{f.sort === k ? (f.desc ? " ▾" : " ▴") : ""}
    </th>
  );
  const pages = Math.max(1, Math.ceil(data.total / PAGE));
  const hasRules = data.rows[0] && Object.keys(RULES).some((k) => k in data.rows[0]);
  const hasLabel = data.rows[0] && "label" in data.rows[0];
  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <select style={{ width: 170 }} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value, page: 0 })} aria-label="Filter by type">
          <option value="">All types</option>
          {types.map((t) => <option key={t} value={t}>{typeName(t)}</option>)}
        </select>
        <input type="search" style={{ width: 230 }} placeholder="Search sender or receiver" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search accounts" />
        <span className="spacer" />
        <a className="btn sm" href={`${API}/api/analysis/${sid}/export.csv?${qs({ threshold, type: f.type, q: f.q })}`}>Download flagged (CSV)</a>
      </div>
      <div className="tablewrap">
        <table>
          <thead><tr>{head("row_id", "Row")}{head("type", "Type")}{head("amount", "Amount", "r")}<th>Sender</th><th>Receiver</th>{hasRules && <th>Rule match</th>}{hasLabel && <th>Known attack</th>}{head("risk", "Risk", "r")}</tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.row_id} className="click" tabIndex={0} onClick={() => onOpen(r.row_id)} onKeyDown={(e) => e.key === "Enter" && onOpen(r.row_id)}>
                <td className="num">{r.row_id}</td><td>{typeName(r.type)}</td><td className="r num">{full(r.amount, currency)}</td>
                <td>{r.nameOrig ?? "n/a"}</td><td>{r.nameDest ?? "n/a"}</td>
                {hasRules && <td>{Object.entries(RULES).filter(([k]) => r[k] === 1).map(([, v]) => v).join(", ") || <span className="faint">None</span>}</td>}
                {hasLabel && <td>{r.label ? "Yes" : "No"}</td>}
                <td><RiskBadge r={r.risk} /></td>
              </tr>
            ))}
            {!data.rows.length && <tr><td colSpan={8} className="muted" style={{ padding: 22, textAlign: "center" }}>No flagged transactions match these filters.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span className="num">{int(data.total)} flagged</span>
        <button className="btn sm" disabled={f.page === 0} onClick={() => setF({ ...f, page: f.page - 1 })}>Previous</button>
        <span className="num">Page {f.page + 1} of {pages}</span>
        <button className="btn sm" disabled={f.page + 1 >= pages} onClick={() => setF({ ...f, page: f.page + 1 })}>Next</button>
      </div>
    </div>
  );
}

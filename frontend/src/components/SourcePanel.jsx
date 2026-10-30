import { useRef, useState } from "react";
import { post, upload } from "../api";
import { Busy, Card, Icon } from "./ui";

const FORMATS = ["CSV", "TSV", "Excel", "JSON", "JSON Lines", "Parquet", ".gz / .zip"];
const ACCEPT = ".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.json,.jsonl,.ndjson,.parquet,.gz,.zip";

/** Four ways to bring data in. Every route ends in the same analysis. */
// An example file with every column the model can use, so new users can see the expected shape of their data.
const TEMPLATE = `step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,newbalanceDest,device_id,sim_change,isFraud
1,PAYMENT,4500,C1001,30000,25500,M2001,0,0,dev-a1,0,0
1,TRANSFER,180000,C1002,180000,0,C3001,5000,185000,dev-b7,1,1
2,CASH_OUT,180000,C3001,185000,5000,C4001,0,180000,dev-c2,0,1
3,CASH_IN,20000,C1003,1000,21000,C5001,90000,70000,dev-d4,0,0
4,PAYMENT,1200,C1001,25500,24300,M2002,0,0,dev-a1,0,0
`;
function downloadTemplate() {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([TEMPLATE], { type: "text/csv" }));
  a.download = "momo-transactions-template.csv"; a.click(); URL.revokeObjectURL(a.href);
}

export default function SourcePanel({ busy, error, onResult, onBusy, onError, threshold, currency }) {
  const [mode, setMode] = useState("file");
  const [over, setOver] = useState(false);
  const [events, setEvents] = useState(null);
  const input = useRef();
  const [db, setDb] = useState({ dialect: "sqlite", host: "", port: "", database: "", username: "", password: "", table: "", query: "" });
  const [api, setApi] = useState({ url: "", method: "GET", headers: "", body: "", records_path: "" });

  const run = async (fn) => {
    onBusy(true); onError("");
    try { onResult(await fn()); } catch (e) { onError(e.message); } finally { onBusy(false); }
  };
  const sendFile = (file) => file && run(() => {
    const fd = new FormData(); fd.append("file", file); if (events) fd.append("events", events);
    fd.append("threshold", threshold); fd.append("currency", currency);
    return upload("/api/analyze/upload", fd);
  });
  const d = (k) => (e) => setDb({ ...db, [k]: e.target.value });
  const a = (k) => (e) => setApi({ ...api, [k]: e.target.value });

  return (
    <Card title="Choose where the transactions come from" sub="Whichever route you pick, the data is mapped to the model's inputs, scored, and interpreted automatically.">
      <div className="seg" style={{ marginBottom: 16 }} role="tablist">
        {[["file", "Upload a file"], ["database", "Connect a database"], ["api", "Pull from an API"], ["sample", "Project sample"]].map(([k, l]) => (
          <button key={k} className={mode === k ? "on" : ""} onClick={() => setMode(k)} disabled={busy}>{l}</button>
        ))}
      </div>

      {mode === "file" && (
        <div className="stack">
          <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
               onDrop={(e) => { e.preventDefault(); setOver(false); sendFile(e.dataTransfer.files[0]); }}>
            <Icon name="file" /><div className="big">Drop a transaction file here</div>
            <div className="formats">{FORMATS.map((f) => <span className="chip" key={f}>{f}</span>)}</div>
            <div className="row" style={{ justifyContent: "center" }}>
              <button className="btn primary" disabled={busy} onClick={() => input.current.click()}>Choose a file</button>
              <button className="btn" type="button" onClick={downloadTemplate} title="A small example file showing every column the model can use">Download a template</button>
            </div>
            <input ref={input} type="file" hidden accept={ACCEPT} onChange={(e) => { sendFile(e.target.files[0]); e.target.value = ""; }} />
            <p className="hint" style={{ maxWidth: 560 }}>Needs at least an <b>amount</b> and a transaction <b>type</b>. Sender, receiver, balances, time and device columns make the analysis richer; common column names are recognised automatically.</p>
          </div>
          <details>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>Optional: add an access-events file (device and SIM-change log)</summary>
            <div className="row" style={{ marginTop: 10 }}>
              <input type="file" accept={ACCEPT} onChange={(e) => setEvents(e.target.files[0] || null)} style={{ maxWidth: 360 }} />
              <span className="hint">Columns such as account_id, device_id, sim_change_event, step. Joined on the sender's account.</span>
            </div>
          </details>
        </div>
      )}

      {mode === "database" && (
        <div className="stack">
          <div className="fields">
            <label className="f">Database type<select value={db.dialect} onChange={d("dialect")}><option value="sqlite">SQLite (file on the server)</option><option value="postgresql">PostgreSQL</option><option value="mysql">MySQL / MariaDB</option></select></label>
            {db.dialect !== "sqlite" && <><label className="f">Host<input type="text" value={db.host} onChange={d("host")} placeholder="db.example.com" /></label>
              <label className="f">Port<input type="text" value={db.port} onChange={d("port")} placeholder={db.dialect === "postgresql" ? "5432" : "3306"} /></label>
              <label className="f">User<input type="text" value={db.username} onChange={d("username")} autoComplete="off" /></label>
              <label className="f">Password<input type="password" value={db.password} onChange={d("password")} autoComplete="new-password" /></label></>}
            <label className="f">{db.dialect === "sqlite" ? "Path to .db file" : "Database name"}<input type="text" value={db.database} onChange={d("database")} placeholder={db.dialect === "sqlite" ? "C:\\data\\momo.db" : "momo"} /></label>
            <label className="f">Table<input type="text" value={db.table} onChange={d("table")} placeholder="transactions" /></label>
          </div>
          <label className="f">Or a SELECT query (replaces the table)<textarea value={db.query} onChange={d("query")} placeholder="SELECT * FROM transactions WHERE created_at >= '2026-10-01'" /></label>
          <div className="note">Read-only: only a single SELECT is accepted, and PostgreSQL / MySQL sessions are opened read-only. Credentials are used for this request and are not stored.</div>
          <div><button className="btn primary" disabled={busy} onClick={() => run(() => post("/api/analyze/database", { ...db, port: db.port ? Number(db.port) : null, threshold, currency }))}>Connect and analyse</button></div>
        </div>
      )}

      {mode === "api" && (
        <div className="stack">
          <div className="fields">
            <label className="f" style={{ gridColumn: "1 / -1" }}>Endpoint URL<input type="text" value={api.url} onChange={a("url")} placeholder="https://momo-platform.example.com/v1/transactions?day=today" /></label>
            <label className="f">Method<select value={api.method} onChange={a("method")}><option>GET</option><option>POST</option></select></label>
            <label className="f">Where the records sit in the JSON (optional)<input type="text" value={api.records_path} onChange={a("records_path")} placeholder="data.transactions" /></label>
          </div>
          <label className="f">Headers, one per line (for tokens)<textarea value={api.headers} onChange={a("headers")} placeholder={"Authorization: Bearer <token>"} /></label>
          {api.method === "POST" && <label className="f">JSON body<textarea value={api.body} onChange={a("body")} placeholder='{"from": "2026-10-01"}' /></label>}
          <div className="note">The server fetches the data once and analyses it. For continuous feeds, use the Live monitor page, where your platform pushes each transaction to the ingest endpoint.</div>
          <div><button className="btn primary" disabled={busy} onClick={() => run(() => post("/api/analyze/api", { ...api, threshold, currency }))}>Fetch and analyse</button></div>
        </div>
      )}

      {mode === "sample" && (
        <div className="stack">
          <p>Analyses the 5,000-transaction labelled sample from the project's feature set. Because it carries real labels and rule flags, it shows every feature of the dashboard, including accuracy and the rule-versus-model comparison.</p>
          <div><button className="btn primary" disabled={busy} onClick={() => run(() => post("/api/analyze/sample", { threshold, currency }))}>Analyse the project sample</button></div>
        </div>
      )}

      {busy && <div style={{ marginTop: 16 }}><Busy text="Mapping columns, building features, scoring and interpreting. Large files can take a minute." /></div>}
      {error && <div className="err" style={{ marginTop: 16 }} role="alert">{error}</div>}
    </Card>
  );
}

import { useEffect, useState } from "react";
import { get } from "../api";
import { passwordOk, useAuth } from "../auth";
import { Card } from "../components/ui";
import { useToast } from "../toast";
import { Avatar, PasswordInput, StrengthMeter } from "./Auth";

const date = (t) => (t ? new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "n/a");

export default function Account() {
  const A = useAuth();
  const toast = useToast();
  const u = A.user;
  const [p, setP] = useState({ name: u.name, organization: u.organization });
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [key, setKey] = useState("");
  const [del, setDel] = useState({ open: false, password: "" });
  const [err, setErr] = useState({});
  const [busy, setBusy] = useState("");
  const [activity, setActivity] = useState(null);
  const loadActivity = () => get("/api/auth/activity").then(setActivity).catch(() => setActivity([]));
  useEffect(() => { loadActivity(); }, [busy]);

  const run = async (id, fn, ok) => {
    setErr((e) => ({ ...e, [id]: "" })); setBusy(id);
    try { await fn(); ok && toast(ok); } catch (x) { setErr((e) => ({ ...e, [id]: x.message })); } finally { setBusy(""); }
  };
  const savePw = (e) => {
    e.preventDefault();
    if (!passwordOk(pw.next)) return setErr({ ...err, pw: "Use at least 8 characters, with a letter and a number." });
    if (pw.next !== pw.confirm) return setErr({ ...err, pw: "The new passwords do not match." });
    run("pw", async () => { await A.changePassword(pw.current, pw.next); setPw({ current: "", next: "", confirm: "" }); }, "Password changed. Other devices were signed out.");
  };
  const base = window.location.origin;
  const curl = `curl -X POST ${base}/api/ingest \\\n  -H "Content-Type: application/json" \\\n  -H "X-API-Key: ${key || "YOUR_API_KEY"}" \\\n  -d '{"type":"CASH_OUT","amount":250000,"nameOrig":"C1001","nameDest":"C2002","device_id":"dev-77"}'`;

  return (
    <>
      <header className="pagehead">
        <div className="row" style={{ gap: 16 }}>
          <Avatar name={u.name} size={56} />
          <div><h1>{u.name}</h1><p>{u.email}{u.organization ? ` · ${u.organization}` : ""}</p></div>
        </div>
        <button className="btn" onClick={() => A.logout().then(() => toast("You have been signed out."))}>Sign out</button>
      </header>

      <div className="stack">
        <div className="grid g2">
          <Card title="Profile" sub="How your name appears in the dashboard.">
            <form className="stack" style={{ gap: 12 }} onSubmit={(e) => { e.preventDefault(); run("profile", () => A.updateProfile(p), "Profile saved."); }}>
              {err.profile && <div className="err" role="alert">{err.profile}</div>}
              <label className="f">Full name<input type="text" value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} maxLength={80} required /></label>
              <label className="f">Organisation<input type="text" value={p.organization} onChange={(e) => setP({ ...p, organization: e.target.value })} maxLength={120} /></label>
              <label className="f">Email address<input type="email" value={u.email} disabled /></label>
              <dl className="kv" style={{ marginTop: 4 }}>
                <dt>Member since</dt><dd>{date(u.created_at)}</dd>
                <dt>Last sign-in</dt><dd>{date(u.last_login)}</dd>
              </dl>
              <div><button className="btn primary" disabled={busy === "profile" || (p.name === u.name && p.organization === u.organization)}>Save changes</button></div>
            </form>
          </Card>

          <Card title="Password" sub="Changing it signs you out on every other device.">
            <form className="stack" style={{ gap: 12 }} onSubmit={savePw}>
              {err.pw && <div className="err" role="alert">{err.pw}</div>}
              <label className="f">Current password<PasswordInput value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" /></label>
              <label className="f">New password<PasswordInput value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" /></label>
              <StrengthMeter pw={pw.next} />
              <label className="f">Confirm new password<PasswordInput value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} autoComplete="new-password" /></label>
              <div><button className="btn primary" disabled={busy === "pw"}>Change password</button></div>
            </form>
          </Card>
        </div>

        <Card title="API key" sub="Lets your own systems send transactions to your live monitor, or call the analysis API, without a browser.">
          <div className="stack" style={{ gap: 12 }}>
            {err.key && <div className="err" role="alert">{err.key}</div>}
            {key ? (
              <div className="keybox">
                <code>{key}</code>
                <button className="btn sm" onClick={() => navigator.clipboard?.writeText(key).then(() => toast("API key copied."))}>Copy</button>
              </div>
            ) : (
              <p>{u.api_key_hint ? <>You have an active key ending in <b className="num">…{u.api_key_hint}</b>. For security it cannot be shown again.</> : "You have no API key yet."}</p>
            )}
            {key && <div className="warn">Copy this key now. It will not be shown again. Anyone with it can send data to your account.</div>}
            <div className="row">
              <button className="btn primary" disabled={busy === "key"} onClick={() => run("key", async () => setKey(await A.createKey()), u.api_key_hint ? "New key created. The old key no longer works." : "API key created.")}>
                {u.api_key_hint ? "Replace key" : "Create API key"}
              </button>
              {u.api_key_hint && <button className="btn" disabled={busy === "key"} onClick={() => run("key", async () => { await A.revokeKey(); setKey(""); }, "API key revoked.")}>Revoke key</button>}
            </div>
            <details>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>Example: send a transaction to your live monitor</summary>
              <pre className="code" style={{ marginTop: 10 }}>{curl}</pre>
            </details>
          </div>
        </Card>

        <Card title="Recent security activity" sub="Sign-ins, password and API key changes on your account over the last 90 days. If you see something you did not do, change your password and sign out of all devices."
          right={<button className="btn sm" onClick={loadActivity}>Refresh</button>}>
          {activity === null ? <p className="muted">Loading...</p> : !activity.length ? <p className="muted">No activity yet.</p> : (
            <div className="tablewrap"><table>
              <thead><tr><th>When</th><th>What happened</th><th>Device</th><th>Network address</th></tr></thead>
              <tbody>{activity.map((a, i) => (
                <tr key={i} className={/failed|throttled/.test(a.event) ? "alert-row" : ""}>
                  <td className="num">{date(a.at)}</td><td>{a.label}</td><td>{a.device}</td><td className="num">{a.ip}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </Card>

        <div className="grid g2">
          <Card title="Sessions" sub="Signed in on a shared or lost computer? End every session at once.">
            {err.all && <div className="err" role="alert" style={{ marginBottom: 10 }}>{err.all}</div>}
            <button className="btn" onClick={() => run("all", A.logoutAll, "Signed out everywhere.")}>Sign out of all devices</button>
          </Card>
          <Card title="Delete account" sub="Removes your account, your API key and any analyses held in memory. This cannot be undone." className="danger-zone">
            {!del.open ? <button className="btn danger-outline" onClick={() => setDel({ open: true, password: "" })}>Delete my account</button> : (
              <form className="stack" style={{ gap: 10 }} onSubmit={(e) => { e.preventDefault(); run("del", () => A.deleteAccount(del.password), "Your account has been deleted."); }}>
                {err.del && <div className="err" role="alert">{err.del}</div>}
                <label className="f">Enter your password to confirm<PasswordInput value={del.password} onChange={(e) => setDel({ ...del, password: e.target.value })} autoComplete="current-password" /></label>
                <div className="row"><button className="btn danger" disabled={busy === "del" || !del.password}>Permanently delete</button><button type="button" className="btn" onClick={() => setDel({ open: false, password: "" })}>Cancel</button></div>
              </form>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

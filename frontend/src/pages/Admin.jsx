// Administration: accounts, platform security counts and recent security events. Administrators are listed in
// MOMO_ADMIN_EMAILS on the server and must have two-step sign-in on; the API enforces both.
import { useEffect, useState } from "react";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { Card, Kpi, Kpis } from "../components/ui";
import { useToast } from "../toast";

const when = (t) => (t ? new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "Never");
const ACTIONS = {
  signout: ["Sign out everywhere", "End every session of {name}? They can sign in again straight away."],
  "reset-2fa": ["Reset two-step sign-in", "Turn off two-step sign-in for {name}? Use this only after confirming their identity, for example when they have lost both their phone and their recovery codes. They will be signed out and should set it up again."],
  disable: ["Disable", "Disable {name}'s account? They are signed out at once and cannot sign in, use API keys or reset their password until re-enabled."],
  enable: ["Re-enable", "Re-enable {name}'s account?"],
  delete: ["Delete", "Permanently delete {name}'s account and everything held for it? This cannot be undone."],
};

export default function Admin({ goAccount }) {
  const { user } = useAuth();
  const toast = useToast();
  const [sum, setSum] = useState(null);
  const [users, setUsers] = useState(null);
  const [events, setEvents] = useState([]);
  const [q, setQ] = useState("");
  const [confirm, setConfirm] = useState(null); // {action, row}
  const [err, setErr] = useState("");

  const load = () => {
    setErr("");
    Promise.all([get("/api/admin/summary"), get("/api/admin/users"), get("/api/admin/events?limit=60")])
      .then(([s, u, e]) => { setSum(s); setUsers(u); setEvents(e); }).catch((x) => setErr(x.message));
  };
  useEffect(load, []);

  if (!user.mfa_enabled) {
    return (
      <>
        <header className="pagehead"><div><h1>Administration</h1><p>Manage accounts and review security events.</p></div></header>
        <div className="warn">For safety, administration needs two-step sign-in on your own account first. <button className="link" onClick={goAccount}>Turn it on from your Account page.</button></div>
      </>
    );
  }

  const run = async () => {
    const { action, row } = confirm;
    setConfirm(null);
    try { await post(`/api/admin/users/${row.id}/${action}`); toast(`${ACTIONS[action][0]}: done for ${row.name}.`); load(); }
    catch (x) { setErr(x.message); }
  };
  const shown = (users || []).filter((u) => !q || `${u.name} ${u.email} ${u.organization}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <header className="pagehead">
        <div><h1>Administration</h1><p>Every account on this platform and its recent security activity. Passwords, codes and keys are never visible here.</p></div>
        <button className="btn" onClick={load}>Refresh</button>
      </header>
      {err && <div className="err" role="alert" style={{ marginBottom: 12 }}>{err}</div>}
      <div className="stack">
        {sum && (
          <Kpis>
            <Kpi value={sum.users} label="Accounts" note={`${sum.new_24h} new in 24 hours`} />
            <Kpi value={`${sum.users ? Math.round((sum.with_2fa / sum.users) * 100) : 0}%`} label="Use two-step sign-in" note={sum.require_2fa ? "Required on this server" : `${sum.with_2fa} of ${sum.users}`} tone={sum.with_2fa === sum.users ? "ok" : ""} />
            <Kpi value={sum.signins_24h} label="Sign-ins, 24 hours" />
            <Kpi value={sum.failed_24h} label="Failed attempts, 24 hours" note={`${sum.throttled_24h} paused for too many tries`} tone={sum.failed_24h > 20 ? "crit" : sum.failed_24h ? "high" : ""} />
            <Kpi value={sum.disabled} label="Disabled accounts" />
          </Kpis>
        )}

        {confirm && (
          <div className="confirm" role="alertdialog" aria-label={ACTIONS[confirm.action][0]}>
            <p>{ACTIONS[confirm.action][1].replace("{name}", confirm.row.name)}</p>
            <div className="row">
              <button className={`btn ${confirm.action === "delete" || confirm.action === "disable" ? "danger" : "primary"}`} onClick={run}>{ACTIONS[confirm.action][0]}</button>
              <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </div>
        )}

        <Card title="Accounts" sub="Newest first. Red rows are disabled. Act on an account only after confirming the person's identity." right={<input type="search" placeholder="Search name, email or organisation" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 280 }} />}>
          {!users ? <p className="muted">Loading...</p> : (
            <div className="tablewrap"><table>
              <thead><tr><th>Name</th><th>Email</th><th>Joined</th><th>Last sign-in</th><th>Two-step</th><th className="r">Failed 24h</th><th>Actions</th></tr></thead>
              <tbody>{shown.map((u) => (
                <tr key={u.id} className={u.disabled ? "alert-row" : ""}>
                  <td><b>{u.name}</b>{u.is_admin && <span className="badge derived" style={{ marginLeft: 6 }}>Admin</span>}{u.organization && <div className="faint">{u.organization}</div>}</td>
                  <td>{u.email}{u.has_api_key && <div className="faint">Has an API key</div>}</td>
                  <td className="num">{when(u.created_at)}</td>
                  <td className="num">{when(u.last_login)}{u.sessions ? <div className="faint">{u.sessions} active session{u.sessions > 1 ? "s" : ""}</div> : null}</td>
                  <td><span className={`badge ${u.mfa_enabled ? "provided" : "default"}`}>{u.mfa_enabled ? "On" : "Off"}</span></td>
                  <td className="r num" style={{ color: u.failed_24h >= 5 ? "var(--crit)" : undefined }}>{u.failed_24h}</td>
                  <td>{u.id === user.id ? <span className="faint">You</span> : (
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <button className="btn sm" onClick={() => setConfirm({ action: "signout", row: u })} disabled={!u.sessions}>Sign out</button>
                      {u.mfa_enabled && <button className="btn sm" onClick={() => setConfirm({ action: "reset-2fa", row: u })}>Reset 2FA</button>}
                      {u.disabled ? <button className="btn sm" onClick={() => setConfirm({ action: "enable", row: u })}>Re-enable</button>
                        : <button className="btn sm danger-outline" onClick={() => setConfirm({ action: "disable", row: u })}>Disable</button>}
                      <button className="btn sm danger-outline" onClick={() => setConfirm({ action: "delete", row: u })}>Delete</button>
                    </div>
                  )}</td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </Card>

        <Card title="Recent security events" sub="The latest 60 across the platform, including failed sign-ins for emails that have no account (a sign of password guessing).">
          <div className="tablewrap"><table>
            <thead><tr><th>When</th><th>Account</th><th>What happened</th><th>Device</th><th>Network address</th></tr></thead>
            <tbody>{events.map((e, i) => (
              <tr key={i} className={/failed|throttled|blocked|disabled/.test(e.event) ? "alert-row" : ""}>
                <td className="num">{when(e.at)}</td><td>{e.account}</td>
                <td>{e.label}{e.detail && <span className="faint"> ({e.detail})</span>}</td><td>{e.device}</td><td className="num">{e.ip}</td>
              </tr>
            ))}</tbody>
          </table></div>
        </Card>
      </div>
    </>
  );
}

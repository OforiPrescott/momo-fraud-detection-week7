import { useEffect, useState } from "react";
import { get } from "./api";
import { useAuth } from "./auth";
import { Icon } from "./components/ui";
import { LiveProvider, useLive } from "./live";
import { useSettings } from "./settings";
import { useToast } from "./toast";
import Account from "./pages/Account";
import Admin from "./pages/Admin";
import Analyze from "./pages/Analyze";
import Auth, { Avatar } from "./pages/Auth";
import TwoStep from "./components/TwoStep";
import Check from "./pages/Check";
import Live from "./pages/Live";
import Model from "./pages/Model";
import Overview from "./pages/Overview";

const NAV = [["overview", "Overview", "overview"], ["analyze", "Analyse data", "analyze"], ["live", "Live monitor", "live"], ["check", "Check a transaction", "check"], ["model", "Model results", "model"], ["account", "Account", "user"]];
const ADMIN_NAV = ["admin", "Administration", "lock"];
const PAGES = [...NAV.map(([k]) => k), "admin"];

export default function App() {
  const { user, config } = useAuth();
  if (user === undefined) return <div className="splash"><img src="/gvsu-logo-white.svg" alt="" /><div className="progress" /></div>;
  // a password-reset link opens the reset form even if this browser is already signed in
  if (!user || window.location.hash.startsWith("#reset=")) return <Auth />;
  // the live stream is per user, so it only opens once someone is signed in
  // a server can require two-step sign-in: until it is on, the account can only set it up (or sign out)
  if (config.require_2fa && !user.mfa_enabled) return <EnforceTwoStep />;
  return <LiveProvider><Shell /></LiveProvider>;
}

function Shell() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const { currency, setCurrency } = useSettings();
  const live = useLive();
  const [page, setPage] = useState(() => (PAGES.includes(window.location.hash.slice(1)) ? window.location.hash.slice(1) : "overview"));
  const [result, setResult] = useState(null);
  const [api, setApi] = useState(null);
  const go = (p) => { setPage(p); window.location.hash = p; window.scrollTo(0, 0); };
  useEffect(() => {
    const ping = () => get("/api/health").then((h) => setApi(h.model_loaded ? "ok" : "nomodel")).catch(() => setApi("down"));
    ping(); const t = setInterval(ping, 15000); return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const onHash = () => { const h = window.location.hash.slice(1); if (PAGES.includes(h)) setPage(h); };
    window.addEventListener("hashchange", onHash); return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const signOut = () => logout().then(() => { window.location.hash = ""; toast("You have been signed out."); });

  return (
    <div className="shell">
        <aside className="rail">
          <div className="brand">
            <img className="logo" src="/gvsu-logo-white.svg" alt="Grand Valley State University" />
            <div className="product">MoMo Fraud and Intrusion Detection<small>Security operations dashboard</small></div>
          </div>
          <nav className="nav" aria-label="Main">
            {(user.is_admin ? [...NAV, ADMIN_NAV] : NAV).map(([k, label, icon]) => (
              <button key={k} className={`${page === k ? "on" : ""} ${k === "account" ? "nav-account" : ""}`} onClick={() => go(k)} aria-label={label} title={label} aria-current={page === k ? "page" : undefined}>
                <Icon name={icon} /><span>{label}</span>{k === "live" && live.replay.running && <span className="live-dot" title="Replay running" />}
              </button>
            ))}
          </nav>
          <div className="foot">
            <label style={{ display: "grid", gap: 4 }}>Currency label
              <select value={currency} onChange={(e) => setCurrency(e.target.value)} style={{ background: "var(--navy-2)", color: "#fff", border: "1px solid var(--navy-3)" }}>
                <option value="">None</option><option value="GHS">GHS (Ghana cedi)</option><option value="USD">$ (US dollar)</option><option value="NGN">₦ (Nigerian naira)</option><option value="KES">KSh (Kenyan shilling)</option><option value="GBP">£ (British pound)</option><option value="EUR">€ (Euro)</option><option value="ZAR">R (South African rand)</option><option value="UGX">USh (Ugandan shilling)</option><option value="TZS">TSh (Tanzanian shilling)</option><option value="XOF">CFA franc</option><option value="XAF">CFA franc BEAC</option><option value="GMD">D (Gambian dalasi)</option><option value="SLL">Le (Sierra Leonean leone)</option><option value="LRD">L$ (Liberian dollar)</option><option value="MWK">MK (Malawian kwacha)</option><option value="ZMW">K (Zambian kwacha)</option><option value="BWP">P (Botswana pula)</option><option value="NAD">N$ (Namibian dollar)</option><option value="MAD">د.م. (Moroccan dirham)</option><option value="EGP">E£ (Egyptian pound)</option><option value="KWD">د.ك (Kuwaiti dinar)</option><option value="AED">د.إ (UAE dirham)</option><option value="SAR">﷼ (Saudi riyal)</option><option value="JPY">¥ (Japanese yen)</option><option value="INR">₹ (Indian rupee)</option><option value="CNY">¥ (Chinese yuan)</option><option value="CAD">C$ (Canadian dollar)</option><option value="AUD">A$ (Australian dollar)</option>
              </select>
            </label>
            <div className="conn"><span className={`dot ${api === "ok" ? "ok" : "bad"}`} />{api === "ok" ? "API connected" : api === "nomodel" ? "API up, model missing" : api === "down" ? "API not reachable" : "Connecting..."}</div>
            <div className="usercard">
              <button className="who" onClick={() => go("account")} title="Account settings">
                <Avatar name={user.name} />
                <span><b>{user.name}</b><small>{user.organization || user.email}</small></span>
              </button>
              <button className="out" onClick={signOut} title="Sign out" aria-label="Sign out"><Icon name="logout" /></button>
            </div>
            <div>Built by <b>Frank Johnfia</b></div>
          </div>
        </aside>
      <main className="main">
        {api === "down" && <div className="err" style={{ marginBottom: 16 }} role="alert">The dashboard cannot reach the API. Start it from the project folder with <code>uvicorn backend.main:app --port 8000</code>.</div>}
        {page === "overview" && <Overview go={go} />}
        {page === "analyze" && <Analyze result={result} setResult={setResult} goLive={() => go("live")} />}
        {page === "live" && <Live analysisResult={result} goAccount={() => go("account")} />}
        {page === "check" && <Check />}
        {page === "model" && <Model />}
        {page === "account" && <Account />}
        {page === "admin" && (user.is_admin ? <Admin goAccount={() => go("account")} /> : <div className="err">Administrators only.</div>)}
        <p className="foot-note">Scores are model estimates. Validate on real, independently labelled data before relying on them operationally.</p>
      </main>
    </div>
  );
}

function EnforceTwoStep() {
  const { user, logout } = useAuth();
  return (
    <div className="gate">
      <div className="gatecard">
        <img src="/gvsu-logo-white.svg" alt="" className="gatelogo" />
        <h1>Turn on two-step sign-in to continue</h1>
        <p>Hello {user.name.split(" ")[0]}. This platform requires two-step sign-in for every account, so a stolen password alone can never open it. It takes about a minute: you need your phone and an authenticator app such as Google Authenticator, Microsoft Authenticator or Authy.</p>
        <TwoStep />
        <p className="fine" style={{ border: 0 }}>Not now? <button className="link" onClick={logout}>Sign out</button></p>
      </div>
    </div>
  );
}

import { useState } from "react";
import { initials, passwordOk, passwordStrength, useAuth } from "../auth";
import { Icon } from "../components/ui";

const FEATURES = [
  ["analyze", "Analyse your own data", "Upload CSV, Excel, JSON or Parquet, or connect a database or REST API. Column names are matched for you."],
  ["live", "Watch transactions live", "Score each transaction the moment it arrives and see alerts, trends and recommendations update in real time."],
  ["check", "Understand every alert", "Each flagged transaction explains which signals raised its risk, such as a new device or a recent SIM change."],
];

export function PasswordInput({ value, onChange, autoComplete, id, placeholder }) {
  const [show, setShow] = useState(false);
  return (
    <div className="pw">
      <input id={id} type={show ? "text" : "password"} value={value} onChange={onChange} autoComplete={autoComplete} placeholder={placeholder} required />
      <button type="button" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"} title={show ? "Hide password" : "Show password"}>
        <Icon name={show ? "eyeOff" : "eye"} />
      </button>
    </div>
  );
}

const STRENGTH = ["Too weak", "Weak", "Fair", "Good", "Strong"];
export function StrengthMeter({ pw }) {
  if (!pw) return <div className="hint">At least 8 characters, with a letter and a number.</div>;
  const s = passwordStrength(pw);
  return (
    <div className="meter" data-s={s}>
      <div className="bars">{[0, 1, 2, 3].map((i) => <i key={i} className={i < s ? "on" : ""} />)}</div>
      <span>{passwordOk(pw) ? STRENGTH[s] : "Needs 8+ characters, a letter and a number"}</span>
    </div>
  );
}

export default function Auth() {
  const { login, register, config } = useAuth();
  const [mode, setMode] = useState(() => (window.location.hash === "#register" ? "register" : "login"));
  const [f, setF] = useState({ name: "", email: "", organization: "", password: "", confirm: "", remember: true });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const swap = (m) => { setMode(m); setErr(""); window.history.replaceState(null, "", m === "register" ? "#register" : "#"); };

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (mode === "register") {
      if (!passwordOk(f.password)) return setErr("Choose a password with at least 8 characters, including a letter and a number.");
      if (f.password !== f.confirm) return setErr("The two passwords do not match.");
    }
    setBusy(true);
    try {
      if (mode === "login") await login(f.email, f.password, f.remember);
      else await register({ name: f.name, email: f.email, organization: f.organization, password: f.password });
      window.history.replaceState(null, "", "#overview");
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="hero">
        <img className="logo" src="/gvsu-logo-white.svg" alt="Grand Valley State University" />
        <div className="pitch">
          <span className="eyebrow">Mobile money security</span>
          <h1>Spot fraud and account takeovers before the money leaves.</h1>
          <p>A machine learning platform that reads transactions together with device and SIM signals to catch SIM-swap takeovers, PIN-sharing abuse and agent collusion.</p>
          <ul className="features">
            {FEATURES.map(([icon, t, d]) => (
              <li key={t}><span className="fi"><Icon name={icon} /></span><div><b>{t}</b><span>{d}</span></div></li>
            ))}
          </ul>
        </div>
        <dl className="stats">
          <div><dt>6.36M</dt><dd>transactions trained on</dd></div>
          <div><dt>99.6%</dt><dd>of attacks caught (recall)</dd></div>
          <div><dt>0.94</dt><dd>AUC-PR on held-out data</dd></div>
        </dl>
      </section>

      <section className="panel">
        <form className="authcard" onSubmit={submit} noValidate={false}>
          <div className="authhead">
            <h2>{mode === "login" ? "Welcome back" : "Create your account"}</h2>
            <p className="muted">{mode === "login" ? "Sign in to continue to your dashboard." : "Free to use. Your analyses stay private to your account."}</p>
          </div>
          {config.registration_open && (
            <div className="seg full" role="tablist">
              <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "on" : ""} onClick={() => swap("login")}>Sign in</button>
              <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "on" : ""} onClick={() => swap("register")}>Create account</button>
            </div>
          )}
          {err && <div className="err" role="alert">{err}</div>}

          {mode === "register" && (
            <>
              <label className="f" htmlFor="a-name">Full name<input id="a-name" type="text" value={f.name} onChange={set("name")} autoComplete="name" required maxLength={80} placeholder="Ama Mensah" /></label>
              <label className="f" htmlFor="a-org"><span>Organisation <span className="faint">(optional)</span></span><input id="a-org" type="text" value={f.organization} onChange={set("organization")} autoComplete="organization" maxLength={120} placeholder="Bank, telco or university" /></label>
            </>
          )}
          <label className="f" htmlFor="a-email">Email address<input id="a-email" type="email" value={f.email} onChange={set("email")} autoComplete="email" required placeholder="you@example.com" /></label>
          <label className="f" htmlFor="a-pw">Password
            <PasswordInput id="a-pw" value={f.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </label>
          {mode === "register" && (
            <>
              <StrengthMeter pw={f.password} />
              <label className="f" htmlFor="a-pw2">Confirm password
                <PasswordInput id="a-pw2" value={f.confirm} onChange={set("confirm")} autoComplete="new-password" />
              </label>
            </>
          )}
          {mode === "login" && (
            <label className="check"><input type="checkbox" checked={f.remember} onChange={set("remember")} />Keep me signed in for 30 days</label>
          )}

          <button className="btn primary lg block" disabled={busy}>
            {busy ? (mode === "login" ? "Signing in..." : "Creating account...") : mode === "login" ? "Sign in" : "Create account"}
          </button>

          {config.registration_open && (
            <p className="switch">
              {mode === "login" ? <>New here? <button type="button" className="link" onClick={() => swap("register")}>Create a free account</button></>
                : <>Already have an account? <button type="button" className="link" onClick={() => swap("login")}>Sign in</button></>}
            </p>
          )}
          <p className="fine"><Icon name="lock" />Passwords are stored as salted hashes. Data you upload is analysed in memory and is visible only to you.</p>
        </form>
      </section>
    </div>
  );
}

export const Avatar = ({ name, size }) => <span className="avatar" style={size ? { width: size, height: size, fontSize: size * 0.4 } : undefined} aria-hidden="true">{initials(name)}</span>;

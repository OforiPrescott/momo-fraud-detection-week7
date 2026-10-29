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
  if (!pw) return <div className="hint">At least 8 characters with a letter and a number. Avoid common passwords and your own name.</div>;
  const s = passwordStrength(pw);
  return (
    <div className="meter" data-s={s}>
      <div className="bars">{[0, 1, 2, 3].map((i) => <i key={i} className={i < s ? "on" : ""} />)}</div>
      <span>{passwordOk(pw) ? STRENGTH[s] : "Needs 8+ characters, a letter and a number"}</span>
    </div>
  );
}

export default function Auth() {
  const { login, loginCode, forgot, resetPassword, register, config } = useAuth();
  const hash = window.location.hash;
  // modes: login | register | forgot (ask for a link) | reset (choose a new password) | code (authenticator step)
  const [mode, setMode] = useState(() => (hash.startsWith("#reset=") ? "reset" : hash === "#register" ? "register" : "login"));
  const [resetToken] = useState(() => (hash.startsWith("#reset=") ? decodeURIComponent(hash.slice(7)) : ""));
  const [f, setF] = useState({ name: "", email: "", organization: "", password: "", confirm: "", remember: true, code: "" });
  const [mfaToken, setMfaToken] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const swap = (m) => {
    if (mode === "reset" && m !== "reset") window.history.replaceState(null, "", "#");  // leave the one-time link behind
    setMode(m); setErr(""); setInfo(""); setF((x) => ({ ...x, password: "", confirm: "", code: "" }));
    window.history.replaceState(null, "", m === "register" ? "#register" : "#");
  };

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setInfo("");
    if (mode === "register" || mode === "reset") {
      if (!passwordOk(f.password)) return setErr("Choose a password with at least 8 characters, including a letter and a number.");
      if (f.password !== f.confirm) return setErr("The two passwords do not match.");
    }
    setBusy(true);
    try {
      if (mode === "login") {
        const step = await login(f.email, f.password, f.remember);
        if (step) { setMfaToken(step.mfa_token); setMode("code"); setUseRecovery(false); return; }
      } else if (mode === "code") {
        await loginCode(mfaToken, f.code);
      } else if (mode === "register") {
        await register({ name: f.name, email: f.email, organization: f.organization, password: f.password });
      } else if (mode === "forgot") {
        const r = await forgot(f.email);
        return setInfo(r.message);
      } else if (mode === "reset") {
        const r = await resetPassword(resetToken, f.password);
        window.dispatchEvent(new Event("momo:signed-out")); // every session was ended by the reset
        swap("login");
        return setInfo(`Your password has been changed and every device was signed out. Sign in with your new password${r.mfa_enabled ? " and your authenticator code" : ""}.`);
      }
      window.history.replaceState(null, "", "#overview");
    } catch (x) {
      setErr(x.message);
      if (mode === "code" && /expired|Too many/.test(x.message)) { setMode("login"); setF((v) => ({ ...v, code: "" })); }
    } finally {
      setBusy(false);
    }
  };

  const HEAD = {
    login: ["Welcome back", "Sign in to continue to your dashboard."],
    register: ["Create your account", "Free to use. Your analyses stay private to your account."],
    forgot: ["Reset your password", "Enter your account's email address and we'll send you a link to choose a new password."],
    reset: ["Choose a new password", "This signs you out on every device. The link works once."],
    code: ["Two-step sign-in", useRecovery ? "Enter one of the recovery codes you saved when you turned on two-step sign-in." : "Open your authenticator app and enter the 6-digit code shown for MoMo Fraud Detection."],
  };
  const BUTTON = { login: ["Sign in", "Signing in..."], register: ["Create account", "Creating account..."], forgot: ["Send reset link", "Sending..."],
    reset: ["Set new password", "Saving..."], code: ["Verify and sign in", "Checking..."] };

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
            <h2>{HEAD[mode][0]}</h2>
            <p className="muted">{HEAD[mode][1]}</p>
          </div>
          {config.registration_open && (mode === "login" || mode === "register") && (
            <div className="seg full" role="tablist">
              <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "on" : ""} onClick={() => swap("login")}>Sign in</button>
              <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "on" : ""} onClick={() => swap("register")}>Create account</button>
            </div>
          )}
          {err && <div className="err" role="alert">{err}</div>}
          {info && <div className="note" role="status">{info}</div>}

          {mode === "register" && (
            <>
              <label className="f" htmlFor="a-name">Full name<input id="a-name" type="text" value={f.name} onChange={set("name")} autoComplete="name" required maxLength={80} placeholder="Ama Mensah" /></label>
              <label className="f" htmlFor="a-org"><span>Organisation <span className="faint">(optional)</span></span><input id="a-org" type="text" value={f.organization} onChange={set("organization")} autoComplete="organization" maxLength={120} placeholder="Bank, telco or university" /></label>
            </>
          )}
          {(mode === "login" || mode === "register" || mode === "forgot") && (
            <label className="f" htmlFor="a-email">Email address<input id="a-email" type="email" value={f.email} onChange={set("email")} autoComplete="email" required placeholder="you@example.com" /></label>
          )}
          {(mode === "login" || mode === "register" || mode === "reset") && (
            <label className="f" htmlFor="a-pw">
              <span className="row" style={{ justifyContent: "space-between" }}>{mode === "reset" ? "New password" : "Password"}
                {mode === "login" && <button type="button" className="link" onClick={() => swap("forgot")}>Forgot password?</button>}
              </span>
              <PasswordInput id="a-pw" value={f.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} />
            </label>
          )}
          {(mode === "register" || mode === "reset") && (
            <>
              <StrengthMeter pw={f.password} />
              <label className="f" htmlFor="a-pw2">Confirm password
                <PasswordInput id="a-pw2" value={f.confirm} onChange={set("confirm")} autoComplete="new-password" />
              </label>
            </>
          )}
          {mode === "code" && (
            <label className="f" htmlFor="a-code">{useRecovery ? "Recovery code" : "6-digit code"}
              <input id="a-code" type="text" value={f.code} onChange={set("code")} required autoFocus
                autoComplete="one-time-code" inputMode={useRecovery ? "text" : "numeric"} maxLength={useRecovery ? 11 : 6}
                placeholder={useRecovery ? "abcde-12345" : "123456"} className="codeinput" />
            </label>
          )}
          {mode === "login" && (
            <label className="check"><input type="checkbox" checked={f.remember} onChange={set("remember")} />Keep me signed in for 30 days</label>
          )}

          <button className="btn primary lg block" disabled={busy || (mode === "forgot" && !!info)}>
            {busy ? BUTTON[mode][1] : BUTTON[mode][0]}
          </button>

          {mode === "code" && (
            <p className="switch">
              <button type="button" className="link" onClick={() => { setUseRecovery(!useRecovery); setF({ ...f, code: "" }); setErr(""); }}>
                {useRecovery ? "Use the code from my app instead" : "Lost your phone? Use a recovery code"}
              </button>
              {" · "}<button type="button" className="link" onClick={() => swap("login")}>Start again</button>
            </p>
          )}
          {(mode === "forgot" || mode === "reset") && (
            <p className="switch">Remembered it? <button type="button" className="link" onClick={() => swap("login")}>Back to sign in</button></p>
          )}
          {config.registration_open && (mode === "login" || mode === "register") && (
            <p className="switch">
              {mode === "login" ? <>New here? <button type="button" className="link" onClick={() => swap("register")}>Create a free account</button></>
                : <>Already have an account? <button type="button" className="link" onClick={() => swap("login")}>Sign in</button></>}
            </p>
          )}
          <p className="fine"><Icon name="lock" />Your password is never stored, only a salted one-way hash of it. Data you upload is analysed in memory and is visible only to you.</p>
        </form>
      </section>
    </div>
  );
}

export const Avatar = ({ name, size }) => <span className="avatar" style={size ? { width: size, height: size, fontSize: size * 0.4 } : undefined} aria-hidden="true">{initials(name)}</span>;

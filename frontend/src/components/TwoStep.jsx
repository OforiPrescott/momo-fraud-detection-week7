// Account page card: turn two-step sign-in (authenticator app) on or off, and manage recovery codes.
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { PasswordInput } from "../pages/Auth";
import { useToast } from "../toast";
import { Card } from "./ui";

function RecoveryCodes({ codes, onDone }) {
  const toast = useToast();
  const text = `MoMo Fraud Detection recovery codes\nEach code works once. Keep them somewhere safe.\n\n${codes.join("\n")}\n`;
  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    a.download = "momo-recovery-codes.txt"; a.click(); URL.revokeObjectURL(a.href);
  };
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="warn"><b>Save these recovery codes now.</b> If you lose your phone, each code signs you in once. They will not be shown again.</div>
      <ol className="codes">{codes.map((c) => <li key={c} className="num">{c}</li>)}</ol>
      <div className="row">
        <button className="btn" onClick={download}>Download as text file</button>
        <button className="btn" onClick={() => navigator.clipboard?.writeText(text).then(() => toast("Recovery codes copied."))}>Copy</button>
        <span className="spacer" />
        <button className="btn primary" onClick={onDone}>I have saved them</button>
      </div>
    </div>
  );
}

export default function TwoStep({ onChange = () => {} }) {
  const { refresh } = useAuth();
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [step, setStep] = useState("idle"); // idle | password | scan | codes | disable | regenerate
  const [pw, setPw] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState(null);
  const [qr, setQr] = useState("");
  const [codes, setCodes] = useState([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => get("/api/auth/2fa").then(setStatus).catch(() => {});
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (setup) QRCode.toDataURL(setup.uri, { margin: 1, width: 220, errorCorrectionLevel: "M" }).then(setQr).catch(() => setQr(""));
  }, [setup]);

  const reset = () => { setStep("idle"); setPw(""); setCode(""); setErr(""); setSetup(null); setQr(""); };
  const run = async (fn) => {
    setErr(""); setBusy(true);
    try { await fn(); } catch (x) { setErr(x.message); } finally { setBusy(false); onChange(); }
  };

  if (!status) return <Card title="Two-step sign-in"><p className="muted">Loading...</p></Card>;

  const sub = status.enabled
    ? "On. Signing in needs your password and a code from your authenticator app."
    : "Off. Add a second step: after your password, a 6-digit code from an app on your phone. A stolen password alone is then not enough.";

  return (
    <Card title="Two-step sign-in" sub={sub} right={<span className={`badge ${status.enabled ? "provided" : "default"}`}>{status.enabled ? "On" : "Off"}</span>}>
      <div className="stack" style={{ gap: 12 }}>
        {err && <div className="err" role="alert">{err}</div>}

        {step === "idle" && !status.enabled && (
          <div><button className="btn primary" onClick={() => setStep("password")}>Turn on two-step sign-in</button></div>
        )}
        {step === "idle" && status.enabled && (
          <>
            <p className={status.recovery_codes_left <= 2 ? "warn" : "hint"}>
              {status.recovery_codes_left} of 8 recovery codes left.{status.recovery_codes_left <= 2 ? " Create new ones soon." : ""}
            </p>
            <div className="row">
              <button className="btn" onClick={() => setStep("regenerate")}>New recovery codes</button>
              <button className="btn danger-outline" onClick={() => setStep("disable")}>Turn off</button>
            </div>
          </>
        )}

        {step === "password" && (
          <form className="stack" style={{ gap: 12 }} onSubmit={(e) => { e.preventDefault(); run(async () => { setSetup(await post("/api/auth/2fa/setup", { password: pw })); setStep("scan"); }); }}>
            <label className="f">Confirm your password to continue<PasswordInput value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></label>
            <div className="row"><button className="btn primary" disabled={busy || !pw}>Continue</button><button type="button" className="btn" onClick={reset}>Cancel</button></div>
          </form>
        )}

        {step === "scan" && setup && (
          <form className="twostep" onSubmit={(e) => { e.preventDefault(); run(async () => { const r = await post("/api/auth/2fa/enable", { code }); setCodes(r.recovery_codes); setStep("codes"); await refresh(); await load(); toast("Two-step sign-in is on."); }); }}>
            <div className="qr">{qr ? <img src={qr} alt="QR code to scan with your authenticator app" width="220" height="220" /> : <div className="muted">QR code unavailable: type the key instead.</div>}</div>
            <div className="stack" style={{ gap: 12 }}>
              <ol className="steps">
                <li>Install an authenticator app on your phone, for example Google Authenticator, Microsoft Authenticator or Authy.</li>
                <li>In the app, add an account and scan this QR code. Can't scan? Choose "enter a setup key" and type: <code className="key">{setup.secret.match(/.{1,4}/g).join(" ")}</code></li>
                <li>Enter the 6-digit code the app now shows.</li>
              </ol>
              <label className="f">6-digit code<input type="text" className="codeinput" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" autoFocus /></label>
              <div className="row"><button className="btn primary" disabled={busy || code.replace(/\D/g, "").length !== 6}>Turn on</button><button type="button" className="btn" onClick={reset}>Cancel</button></div>
            </div>
          </form>
        )}

        {step === "codes" && <RecoveryCodes codes={codes} onDone={reset} />}

        {(step === "disable" || step === "regenerate") && (
          <form className="stack" style={{ gap: 12 }} onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              if (step === "disable") {
                await post("/api/auth/2fa/disable", { password: pw, code });
                await refresh(); await load(); reset(); toast("Two-step sign-in is off.");
              } else {
                const r = await post("/api/auth/2fa/recovery-codes", { password: pw });
                setCodes(r.recovery_codes); setStep("codes"); setPw(""); await load();
              }
            });
          }}>
            {step === "disable" && <div className="warn">Turning this off means a password alone can open your account again.</div>}
            {step === "regenerate" && <div className="note">New codes replace all your old ones, which stop working.</div>}
            <label className="f">Your password<PasswordInput value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></label>
            {step === "disable" && <label className="f">Code from your app (or a recovery code)<input type="text" className="codeinput" value={code} onChange={(e) => setCode(e.target.value)} maxLength={11} autoComplete="one-time-code" /></label>}
            <div className="row">
              <button className={`btn ${step === "disable" ? "danger" : "primary"}`} disabled={busy || !pw || (step === "disable" && !code)}>{step === "disable" ? "Turn off two-step sign-in" : "Create new codes"}</button>
              <button type="button" className="btn" onClick={reset}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}

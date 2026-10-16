import { useEffect, useState } from "react";
import { get } from "./api";
import { Icon } from "./components/ui";
import { useLive } from "./live";
import { useSettings } from "./settings";
import Analyze from "./pages/Analyze";
import Check from "./pages/Check";
import Live from "./pages/Live";
import Model from "./pages/Model";
import Overview from "./pages/Overview";

const NAV = [["overview", "Overview", "overview"], ["analyze", "Analyse data", "analyze"], ["live", "Live monitor", "live"], ["check", "Check a transaction", "check"], ["model", "Model results", "model"]];

export default function App() {
  const { currency, setCurrency } = useSettings();
  const live = useLive();
  const [page, setPage] = useState(() => window.location.hash.slice(1) || "overview");
  const [result, setResult] = useState(null);
  const [api, setApi] = useState(null);
  const go = (p) => { setPage(p); window.location.hash = p; window.scrollTo(0, 0); };
  useEffect(() => { get("/api/health").then((h) => setApi(h.model_loaded ? "ok" : "nomodel")).catch(() => setApi("down")); const t = setInterval(() => get("/api/health").then((h) => setApi(h.model_loaded ? "ok" : "nomodel")).catch(() => setApi("down")), 15000); return () => clearInterval(t); }, []);

  return (
    <div className="shell">
        <aside className="rail">
          <div className="brand">
            <img className="logo" src="/gvsu-logo-white.svg" alt="Grand Valley State University" />
            <div className="product">MoMo Fraud and Intrusion Detection<small>Security operations dashboard</small></div>
          </div>
          <nav className="nav" aria-label="Main">
            {NAV.map(([k, label, icon]) => (
              <button key={k} className={page === k ? "on" : ""} onClick={() => go(k)} aria-current={page === k ? "page" : undefined}>
                <Icon name={icon} />{label}{k === "live" && live.replay.running && <span className="live-dot" title="Replay running" />}
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
            <div>Built by <b>Frank Johnfia</b></div>
          </div>
        </aside>
      <main className="main">
        {api === "down" && <div className="err" style={{ marginBottom: 16 }} role="alert">The dashboard cannot reach the API. Start it from the project folder with <code>uvicorn backend.main:app --port 8000</code>.</div>}
        {page === "overview" && <Overview go={go} />}
        {page === "analyze" && <Analyze result={result} setResult={setResult} goLive={() => go("live")} />}
        {page === "live" && <Live analysisResult={result} />}
        {page === "check" && <Check />}
        {page === "model" && <Model />}
        <p className="foot-note">Scores are model estimates. Validate on real, independently labelled data before relying on them operationally.</p>
      </main>
    </div>
  );
}

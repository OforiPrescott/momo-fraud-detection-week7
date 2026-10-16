export const int = (x) => Math.round(x ?? 0).toLocaleString();
export const pct = (x, d = 1) => `${(x ?? 0).toFixed(d)}%`;
export function money(x, cur = "") {
  const a = Math.abs(x ?? 0);
  const s = a >= 1e9 ? `${(x / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(x / 1e6).toFixed(2)}M` : a >= 1e4 ? `${(x / 1e3).toFixed(1)}K` : Math.round(x).toLocaleString();
  return `${cur}${s}`;
}
export const full = (x, cur = "") => `${cur}${Number(x).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
export const riskColor = (r) => (r >= 0.9 ? "var(--crit)" : r >= 0.5 ? "var(--high)" : r >= 0.3 ? "var(--med)" : "var(--low)");
export const typeName = (t) => String(t ?? "").replace("_", " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
export const timeOf = (iso) => new Date(iso).toLocaleTimeString([], { hour12: false });
export const PALETTE = { navy: "#0c2340", blue: "#0065a4", low: "#2f9e8f", med: "#d99a1c", high: "#dc5f2b", crit: "#b3283f", grey: "#c4ccd6" };

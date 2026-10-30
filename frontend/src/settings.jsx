import { createContext, useContext, useEffect, useState } from "react";

const Ctx = createContext({ currency: "", setCurrency: () => {}, theme: "system", setTheme: () => {} });
export const useSettings = () => useContext(Ctx);

const read = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const write = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode: keep it for this visit */ } };

// Currency label is cosmetic (PaySim amounts carry no currency). Theme: "system" follows the computer's
// light/dark setting; "light" or "dark" overrides it. Both are remembered on this device only.
export function SettingsProvider({ children }) {
  const [currency, setCurrency] = useState(() => read("momo.currency", "GHS"));
  const [theme, setTheme] = useState(() => read("momo.theme", "system"));
  useEffect(() => write("momo.currency", currency), [currency]);
  useEffect(() => {
    write("momo.theme", theme);
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [theme]);
  return <Ctx.Provider value={{ currency, setCurrency, theme, setTheme }}>{children}</Ctx.Provider>;
}

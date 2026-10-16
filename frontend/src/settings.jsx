import { createContext, useContext, useEffect, useState } from "react";

const Ctx = createContext({ currency: "", setCurrency: () => {} });
export const useSettings = () => useContext(Ctx);

// Currency label is cosmetic (PaySim amounts carry no currency); stored so it survives reloads.
export function SettingsProvider({ children }) {
  const [currency, setCurrency] = useState(() => localStorage.getItem("momo.currency") ?? "GHS");
  useEffect(() => localStorage.setItem("momo.currency", currency), [currency]);
  return <Ctx.Provider value={{ currency, setCurrency }}>{children}</Ctx.Provider>;
}

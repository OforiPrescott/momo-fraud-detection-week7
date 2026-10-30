// Appearance: follow the device (Auto), or always Light / Dark. Remembered on this device.
import { useSettings } from "../settings";

const THEMES = [["system", "Auto"], ["light", "Light"], ["dark", "Dark"]];
export default function ThemeSwitch({ light }) {
  const { theme, setTheme } = useSettings();
  return (
    <div className={`themeswitch ${light ? "on-light" : ""}`} role="radiogroup" aria-label="Appearance">
      {THEMES.map(([k, label]) => (
        <button key={k} role="radio" aria-checked={theme === k} className={theme === k ? "on" : ""} onClick={() => setTheme(k)}
          title={k === "system" ? "Follow this device's light or dark setting" : `Always ${label.toLowerCase()}`}>{label}</button>
      ))}
    </div>
  );
}

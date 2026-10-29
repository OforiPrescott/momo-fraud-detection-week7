// Who is signed in. The session itself is an HttpOnly cookie set by the API; this only mirrors the user.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { get, post } from "./api";

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = still checking, null = signed out
  const [config, setConfig] = useState({ registration_open: true });

  useEffect(() => {
    get("/api/auth/me").then(setUser).catch(() => setUser(null));
    get("/api/auth/config").then(setConfig).catch(() => {});
    const out = () => setUser(null);
    window.addEventListener("momo:signed-out", out);
    return () => window.removeEventListener("momo:signed-out", out);
  }, []);

  const login = useCallback((email, password, remember) => post("/api/auth/login", { email, password, remember }).then(setUser), []);
  const register = useCallback((form) => post("/api/auth/register", form).then(setUser), []);
  const logout = useCallback(() => post("/api/auth/logout").catch(() => {}).then(() => setUser(null)), []);
  const logoutAll = useCallback(() => post("/api/auth/logout-all").then(() => setUser(null)), []);
  const updateProfile = useCallback((p) => post("/api/auth/profile", p).then(setUser), []);
  const changePassword = useCallback((current_password, new_password) => post("/api/auth/password", { current_password, new_password }), []);
  const createKey = useCallback(() => post("/api/auth/api-key").then((r) => { setUser((u) => ({ ...u, api_key_hint: r.api_key_hint })); return r.api_key; }), []);
  const revokeKey = useCallback(() => post("/api/auth/api-key/revoke").then(() => setUser((u) => ({ ...u, api_key_hint: null }))), []);
  const deleteAccount = useCallback((password) => post("/api/auth/delete", { password }).then(() => setUser(null)), []);

  return (
    <Ctx.Provider value={{ user, config, login, register, logout, logoutAll, updateProfile, changePassword, createKey, revokeKey, deleteAccount }}>
      {children}
    </Ctx.Provider>
  );
}

/** 0-4 strength estimate shown under password fields. */
export function passwordStrength(pw) {
  if (!pw) return 0;
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
  if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) s = Math.min(s, 1);
  return s;
}
export const passwordOk = (pw) => pw.length >= 8 && /[A-Za-z]/.test(pw) && /\d/.test(pw);
export const initials = (name = "") => name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";

// All calls to the FastAPI backend live here, so every page uses the same base URL and error handling.
// Dev:  `npm run dev` (port 5173) proxies /api to http://localhost:8000 (see vite.config.js)
// Prod: `npm run build`, FastAPI serves the dashboard itself -> same origin
// The sign-in session travels in an HttpOnly cookie, so no token is ever handled here.
export const API = import.meta.env.VITE_API_URL ?? "";

async function handle(res) {
  if (res.ok) return res.json();
  let msg = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (body.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch { /* keep generic message */ }
  // an expired session anywhere sends the user back to the sign-in screen
  if (res.status === 401 && !res.url.includes("/api/auth/")) window.dispatchEvent(new Event("momo:signed-out"));
  const err = new Error(msg);
  err.status = res.status;
  throw err;
}

const opts = { credentials: "same-origin" };
export const get = (path) => fetch(API + path, opts).then(handle);
export const post = (path, body) =>
  fetch(API + path, { ...opts, method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) }).then(handle);
export const upload = (path, form) => fetch(API + path, { ...opts, method: "POST", body: form }).then(handle);
export const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v != null)).toString();

// All calls to the FastAPI backend live here, so every page uses the same base URL and error handling.
// Dev:  `npm run dev` (port 5173) -> API at http://localhost:8000
// Prod: `npm run build`, FastAPI serves the dashboard itself -> same origin
export const API = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

async function handle(res) {
  if (res.ok) return res.json();
  let msg = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (body.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch { /* keep generic message */ }
  throw new Error(msg);
}

export const get = (path) => fetch(API + path).then(handle);
export const post = (path, body) =>
  fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(handle);
export const upload = (path, form) => fetch(API + path, { method: "POST", body: form }).then(handle);
export const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v != null)).toString();

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the dashboard on :5173 and proxies /api to the API on :8000, so the
// sign-in cookie is same-origin in development exactly as in production. changeOrigin stays false so the
// API sees Host=localhost:5173, matching the browser's Origin (the API refuses cross-site writes).
// `npm run build` writes frontend/dist, which backend/main.py serves itself.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } } },
});

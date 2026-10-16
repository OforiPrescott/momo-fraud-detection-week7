import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the dashboard on :5173 and talks to the API on :8000.
// `npm run build` writes frontend/dist, which backend/main.py serves itself.
export default defineConfig({ plugins: [react()], server: { port: 5173 } });

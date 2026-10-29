import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/source-serif-4";
import "@fontsource-variable/public-sans";
import "./styles.css";
import App from "./App.jsx";
import { AuthProvider } from "./auth.jsx";
import { SettingsProvider } from "./settings.jsx";
import { ToastProvider } from "./toast.jsx";

createRoot(document.getElementById("root")).render(
  <SettingsProvider>
    <ToastProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ToastProvider>
  </SettingsProvider>
);
if ('serviceWorker' in navigator) { window.addEventListener('load', () => { navigator.serviceWorker.register('/service-worker.js').catch(()=>{}); }); }

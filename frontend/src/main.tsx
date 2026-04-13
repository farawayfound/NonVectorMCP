import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/index.css";

// #region agent log
fetch("/api/health")
  .then((r) => r.json())
  .then((h) => {
    fetch("http://127.0.0.1:7517/ingest/bd8fe758-d961-4288-a376-8a2704de8add", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "c921f0" },
      body: JSON.stringify({
        sessionId: "c921f0",
        location: "main.tsx:boot",
        message: "client health vs page origin",
        hypothesisId: "H_D",
        runId: "pre-fix",
        data: {
          page_href: typeof window !== "undefined" ? window.location.href : "",
          health_frontend: h?.frontend ?? null,
        },
        timestamp: Date.now(),
      }),
    }).catch(() => {});
  })
  .catch(() => {});
// #endregion

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

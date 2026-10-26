import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";

// Entry point; the landing page and the run view are added next.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <main className="p-8">Rookwise</main>
  </StrictMode>,
);

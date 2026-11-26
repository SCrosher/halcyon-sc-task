import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { DevModeProvider } from "./hooks/useDevMode";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DevModeProvider>
      <App />
    </DevModeProvider>
  </StrictMode>,
);

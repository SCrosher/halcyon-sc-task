import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** Same fallback the agent API uses locally when AGENT_API_TOKENS isn't set (agent-api/app/config.py). */
const LOCAL_API_TOKEN = "local-dev-token";

/** First AGENT_API_TOKENS entry from the repo-root .env, so `npm run dev` connects with zero setup. */
function localAgentToken(): string {
  try {
    const env = readFileSync(resolve(import.meta.dirname, "..", ".env"), "utf8");
    const line = env.split(/\r?\n/).find((l) => /^\s*AGENT_API_TOKENS\s*=/.test(l));
    const value = line
      ?.split("=")
      .slice(1)
      .join("=")
      .trim()
      .replace(/^(['"])(.*)\1$/, "$2");
    return value?.split(",")[0]?.trim() || LOCAL_API_TOKEN;
  } catch {
    return LOCAL_API_TOKEN;
  }
}

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  server: { port: 5173 },
  // Dev server only, so `npm run dev` works here as well as from the repo root. `vite build` never sees
  // this; deployed builds get the token from scripts/deploy.mjs.
  define: command === "serve" ? { "import.meta.env.VITE_AGENT_API_TOKEN": JSON.stringify(localAgentToken()) } : {},
}));

/** Build-time environment, set by scripts/deploy.mjs (VITE_APP_ENV). Unset in `npm run dev`. */
export type AppEnv = "local" | "staging" | "production";

const raw = import.meta.env.VITE_APP_ENV?.trim();

export const APP_ENV: AppEnv = raw === "staging" || raw === "production" ? raw : "local";

/** The agent API this build was deployed against, if any. */
export const DEPLOYED_API_URL = import.meta.env.VITE_AGENT_API_URL?.trim() || undefined;

export const LOCAL_API_URL = "http://localhost:8000";

/**
 * Default agent API token, set by `npm run dev` and the deploy script.
 * KNOWN, ACCEPTED SECURITY FLAW (demo app): in deployed builds this is visible in the public bundle.
 */
export const DEFAULT_AGENT_TOKEN = import.meta.env.VITE_AGENT_API_TOKEN?.trim() ?? "";

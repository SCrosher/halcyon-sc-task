/**
 * Cloudflare Worker fronting the agent API container.
 * Every request is forwarded to a single container instance running the Python app
 * (turns are coordinated in-process, so there must only ever be one instance).
 */
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  AGENT_API: DurableObjectNamespace<AgentApiContainer>;
  // Plain vars (wrangler.json "vars", plus ones set by scripts/deploy.mjs)
  HALCYON_ENV: string;
  ANTHROPIC_MODEL: string;
  AGENT_EFFORT: string;
  ANTHROPIC_FALLBACKS: string;
  MEMBER_TIMEZONE: string;
  CORS_ORIGINS: string;
  CLOUDFLARE_ACCOUNT_ID: string;
  AGENT_D1_DATABASE_ID: string;
  MOCK_SERVICES_URL: string;
  // Secrets
  ANTHROPIC_API_KEY: string;
  AGENT_API_TOKENS: string;
  D1_API_TOKEN: string;
  MOCK_SERVICES_TOKEN: string;
}

const PASSED_TO_CONTAINER = [
  "HALCYON_ENV",
  "ANTHROPIC_MODEL",
  "AGENT_EFFORT",
  "ANTHROPIC_FALLBACKS",
  "MEMBER_TIMEZONE",
  "CORS_ORIGINS",
  "CLOUDFLARE_ACCOUNT_ID",
  "AGENT_D1_DATABASE_ID",
  "MOCK_SERVICES_URL",
  "ANTHROPIC_API_KEY",
  "AGENT_API_TOKENS",
  "D1_API_TOKEN",
  "MOCK_SERVICES_TOKEN",
] as const satisfies readonly (keyof Env)[];

export class AgentApiContainer extends Container<Env> {
  defaultPort = 8000;
  sleepAfter = "30m";

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = Object.fromEntries(PASSED_TO_CONTAINER.map((key) => [key, env[key] ?? ""]));
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return getContainer(env.AGENT_API).fetch(request);
  },
} satisfies ExportedHandler<Env>;

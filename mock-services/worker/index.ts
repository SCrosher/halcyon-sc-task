/**
 * Cloudflare Worker fronting the mock-services container.
 * Every request is forwarded to a single container instance running the Python app.
 */
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  MOCK_SERVICES: DurableObjectNamespace<MockServicesContainer>;
  // Plain vars (wrangler.json "vars", plus ones set by scripts/deploy.mjs)
  HALCYON_ENV: string;
  CLOUDFLARE_ACCOUNT_ID: string;
  MOCK_D1_DATABASE_ID: string;
  // Secrets
  D1_API_TOKEN: string;
  MOCK_SERVICES_TOKEN: string;
}

export class MockServicesContainer extends Container<Env> {
  defaultPort = 8000;
  sleepAfter = "30m";

  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = {
      HALCYON_ENV: env.HALCYON_ENV,
      CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID,
      MOCK_D1_DATABASE_ID: env.MOCK_D1_DATABASE_ID,
      D1_API_TOKEN: env.D1_API_TOKEN,
      MOCK_SERVICES_TOKEN: env.MOCK_SERVICES_TOKEN,
    };
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    return getContainer(env.MOCK_SERVICES).fetch(request);
  },
} satisfies ExportedHandler<Env>;

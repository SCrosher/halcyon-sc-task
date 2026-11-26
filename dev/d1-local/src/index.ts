/**
 * Local stand-in for the Cloudflare D1 REST API, for local development only.
 *
 * Serves POST /client/v4/accounts/{account}/d1/database/{database_id}/query with the
 * same request and response shapes as Cloudflare, backed by wrangler's local D1
 * (data persisted under .local/d1 at the repo root). Run by `npm run dev`; this
 * Worker is never deployed.
 */

interface Env {
  MOCK_SERVICES_DB: D1Database;
  AGENT_DB: D1Database;
}

interface Statement {
  sql: string;
  params?: unknown[];
}

const QUERY_PATH = /^\/client\/v4\/accounts\/[^/]+\/d1\/database\/([^/]+)\/query$/;

function databases(env: Env): Record<string, D1Database> {
  // Keys are the database_id values in wrangler.json.
  return { "halcyon-mock-services-local": env.MOCK_SERVICES_DB, "halcyon-agent-local": env.AGENT_DB };
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

function failure(status: number, message: string): Response {
  return json({ success: false, errors: [{ code: 7500, message }], messages: [], result: [] }, status);
}

function isStatement(value: unknown): value is Statement {
  const s = value as Statement;
  return typeof s?.sql === "string" && (s.params === undefined || Array.isArray(s.params));
}

function prepare(db: D1Database, statement: Statement): D1PreparedStatement {
  const prepared = db.prepare(statement.sql);
  return statement.params?.length ? prepared.bind(...statement.params) : prepared;
}

function shape(result: D1Result) {
  return { results: result.results ?? [], meta: result.meta, success: result.success };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return json({ status: "ok" });

    const match = url.pathname.match(QUERY_PATH);
    if (!match) return failure(404, `Not found: ${url.pathname}`);
    if (request.method !== "POST") return failure(405, "Method not allowed");
    const db = databases(env)[decodeURIComponent(match[1])];
    if (!db) return failure(404, `Unknown local database "${match[1]}"`);

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return failure(400, "Request body must be JSON");
    }

    try {
      const { batch } = body as { batch?: unknown };
      if (batch !== undefined) {
        if (!Array.isArray(batch) || !batch.every(isStatement)) return failure(400, "Invalid batch");
        const results = await db.batch(batch.map((s) => prepare(db, s)));
        return json({ success: true, errors: [], messages: [], result: results.map(shape) });
      }
      if (!isStatement(body)) return failure(400, "Body must contain sql (and optional params)");
      const result = await prepare(db, body).all();
      return json({ success: true, errors: [], messages: [], result: [shape(result)] });
    } catch (error) {
      return failure(400, error instanceof Error ? error.message : String(error));
    }
  },
} satisfies ExportedHandler<Env>;

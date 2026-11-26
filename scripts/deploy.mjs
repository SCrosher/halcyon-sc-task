#!/usr/bin/env node
/**
 * Deploy all of Halcyon to one environment on Cloudflare (Workers + Containers + D1),
 * authenticating with an account id and API token - no `wrangler login`.
 *
 *   node scripts/deploy.mjs <staging|production> [--db-only] [--yes]
 *
 * Deploys, in order: mock-services -> agent-api -> test-ui. Each environment has its own
 * workers (halcyon-*-<env>), D1 databases and credentials, read only from `.env.<env>` at the
 * repo root (process environment variables win, for CI). Container deploys need Docker running.
 *
 * You provide ANTHROPIC_API_KEY, AGENT_API_TOKENS, CLOUDFLARE_API_TOKEN and D1_API_TOKEN. On first
 * use the script creates `.env.<env>` if needed, looks up CLOUDFLARE_ACCOUNT_ID from the token and
 * generates MOCK_SERVICES_TOKEN, writing both back so later deploys reuse them.
 *
 *   --db-only  create the environment's D1 databases if needed and apply migrations, then stop
 *   --yes      skip the confirmation prompt (required for production when not on a terminal)
 */
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { createInterface } from "node:readline/promises";
import {
  ROOT,
  ensureEnvFile,
  fail,
  firstToken,
  loadEnvFile,
  npm,
  setEnvValue,
  wrangler as runWrangler,
} from "./lib.mjs";

const ENVIRONMENTS = ["staging", "production"];

const MOCK = {
  dir: "mock-services",
  databaseIdVar: "MOCK_D1_DATABASE_ID",
  secrets: ["D1_API_TOKEN", "MOCK_SERVICES_TOKEN"],
};
const AGENT = {
  dir: "agent-api",
  databaseIdVar: "AGENT_D1_DATABASE_ID",
  secrets: ["ANTHROPIC_API_KEY", "AGENT_API_TOKENS", "D1_API_TOKEN", "MOCK_SERVICES_TOKEN"],
};
const UI = { dir: "test-ui" };
// Values you provide; CLOUDFLARE_ACCOUNT_ID and MOCK_SERVICES_TOKEN are filled in automatically.
const PROVIDED = ["ANTHROPIC_API_KEY", "AGENT_API_TOKENS", "CLOUDFLARE_API_TOKEN", "D1_API_TOKEN"];

// ---- arguments & environment ---------------------------------------------------------------

const args = process.argv.slice(2);
const environment = args.find((a) => !a.startsWith("--"));
const dbOnly = args.includes("--db-only");
const assumeYes = args.includes("--yes");
if (!ENVIRONMENTS.includes(environment)) {
  fail(`Usage: node scripts/deploy.mjs <${ENVIRONMENTS.join("|")}> [--db-only] [--yes]`);
}

const envFile = ensureEnvFile(environment);
const env = { ...loadEnvFile(envFile), ...process.env };

/** Fill in a value the script owns, persisting it unless it came from the process environment (CI). */
function remember(key, value) {
  env[key] = value;
  if (!process.env[key]) setEnvValue(envFile, key, value);
}

function ensureNodeModules(dir) {
  if (!existsSync(join(ROOT, dir, "node_modules")))
    npm(["install", "--no-fund", "--no-audit"], { cwd: join(ROOT, dir), env });
}

function wrangler(dir, wranglerArgs, options = {}) {
  ensureNodeModules(dir);
  return runWrangler(dir, wranglerArgs, { env, ...options });
}

function readConfig(dir) {
  return JSON.parse(readFileSync(join(ROOT, dir, "wrangler.json"), "utf8"));
}

// ---- preflight -----------------------------------------------------------------------------

async function preflight() {
  const needed = dbOnly ? ["CLOUDFLARE_API_TOKEN"] : PROVIDED;
  const missing = needed.filter((name) => !env[name]);
  if (missing.length) fail(`Fill in ${missing.join(", ")} in ${envFile}.`);
  if (!dbOnly) {
    const docker = spawnSync("docker", ["info"], { stdio: "ignore" });
    if (docker.status !== 0) fail("Docker is not running; it is needed to build the container images.");
    if (!existsSync(join(ROOT, UI.dir, "package.json"))) fail(`${UI.dir}/package.json not found.`);
  }
  if (environment === "production" && !assumeYes) {
    if (!process.stdin.isTTY) fail("Refusing to deploy production non-interactively without --yes.");
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    const answer = await rl.question(`Deploying to PRODUCTION. Type "production" to continue: `);
    rl.close();
    if (answer.trim() !== "production") fail("Cancelled.");
  }
}

// ---- generated values ----------------------------------------------------------------------

async function resolveAccountId() {
  if (env.CLOUDFLARE_ACCOUNT_ID) return;
  const response = await fetch("https://api.cloudflare.com/client/v4/accounts", {
    headers: { Authorization: `Bearer ${env.CLOUDFLARE_API_TOKEN}` },
  });
  const body = await response.json().catch(() => ({}));
  const accounts = response.ok ? (body.result ?? []) : [];
  if (accounts.length !== 1) {
    const found = accounts.map((a) => `${a.name} (${a.id})`).join(", ");
    fail(
      `Could not pick a Cloudflare account from the token${found ? `; it can access: ${found}` : ""}. ` +
        `Set CLOUDFLARE_ACCOUNT_ID in ${envFile}.`,
    );
  }
  remember("CLOUDFLARE_ACCOUNT_ID", accounts[0].id);
  console.log(`→ Using Cloudflare account ${accounts[0].name}`);
}

function ensureMockServicesToken() {
  if (env.MOCK_SERVICES_TOKEN) return;
  remember("MOCK_SERVICES_TOKEN", randomBytes(32).toString("hex"));
  console.log(`→ Generated MOCK_SERVICES_TOKEN (saved to ${envFile})`);
}

// ---- Cloudflare ----------------------------------------------------------------------------

/** Public URL of a project in this environment: its custom domain in wrangler.json. */
function projectUrl(dir) {
  const domain = readConfig(dir).env[environment].routes?.find((r) => r.custom_domain)?.pattern;
  if (!domain) fail(`${dir}/wrangler.json has no custom domain for ${environment}.`);
  return `https://${domain}`;
}

/** Create the project's D1 database for this environment if needed, record its id, apply migrations. */
function ensureDatabase(project) {
  const configPath = join(ROOT, project.dir, "wrangler.json");
  const config = readConfig(project.dir);
  const binding = config.env[environment].d1_databases[0];

  if (!binding.database_id) {
    const find = () =>
      JSON.parse(wrangler(project.dir, ["d1", "list", "--json"], { capture: true })).find(
        (d) => d.name === binding.database_name,
      );
    let database = find();
    if (!database) {
      console.log(`\n→ Creating D1 database ${binding.database_name}`);
      wrangler(project.dir, ["d1", "create", binding.database_name]);
      database = find();
    }
    if (!database?.uuid) fail(`Could not find the id of D1 database ${binding.database_name}`);
    binding.database_id = database.uuid;
    writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n");
    console.log(`  Recorded its id in ${project.dir}/wrangler.json (commit this).`);
  }

  console.log(`\n→ Applying migrations to ${binding.database_name}`);
  wrangler(project.dir, ["d1", "migrations", "apply", binding.database_name, "--remote", "--env", environment]);
  return binding.database_id;
}

/** Deploy a container project: vars on the command line, secrets through a temporary file. */
function deployContainer(project, vars) {
  const secretsDir = mkdtempSync(join(tmpdir(), "halcyon-secrets-"));
  const secretsFile = join(secretsDir, "secrets.json");
  try {
    writeFileSync(secretsFile, JSON.stringify(Object.fromEntries(project.secrets.map((k) => [k, env[k]]))), {
      mode: 0o600,
    });
    const varArgs = Object.entries(vars).flatMap(([k, v]) => ["--var", `${k}:${v}`]);
    console.log(`\n→ Deploying ${readConfig(project.dir).env[environment].name} (builds the container image)`);
    wrangler(project.dir, [
      "deploy",
      "--env",
      environment,
      "--secrets-file",
      secretsFile,
      "--containers-rollout",
      "immediate",
      ...varArgs,
    ]);
  } finally {
    rmSync(secretsDir, { recursive: true, force: true });
  }
}

// ---- main ----------------------------------------------------------------------------------

await preflight();
await resolveAccountId();
if (!dbOnly) ensureMockServicesToken();
console.log(`\n=== Halcyon ${environment}${dbOnly ? " (databases only)" : ""} ===`);

const mockDatabaseId = ensureDatabase(MOCK);
const agentDatabaseId = ensureDatabase(AGENT);
if (dbOnly) {
  console.log(`\n✔ ${environment} databases ready`);
  process.exit(0);
}

const mockUrl = projectUrl(MOCK.dir);
const agentUrl = projectUrl(AGENT.dir);
const uiUrl = projectUrl(UI.dir);

deployContainer(MOCK, { CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID, [MOCK.databaseIdVar]: mockDatabaseId });
deployContainer(AGENT, {
  CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID,
  [AGENT.databaseIdVar]: agentDatabaseId,
  MOCK_SERVICES_URL: mockUrl,
});

console.log(`\n→ Building ${UI.dir} against ${agentUrl}`);
ensureNodeModules(UI.dir);
// KNOWN, ACCEPTED SECURITY FLAW (demo app): the agent API token is baked into the public UI bundle.
const uiBuildEnv = {
  ...env,
  VITE_APP_ENV: environment,
  VITE_AGENT_API_URL: agentUrl,
  VITE_AGENT_API_TOKEN: firstToken(env.AGENT_API_TOKENS),
};
npm(["run", "build"], { cwd: join(ROOT, UI.dir), env: uiBuildEnv });
console.log(`\n→ Deploying ${readConfig(UI.dir).env[environment].name}`);
wrangler(UI.dir, ["deploy", "--env", environment]);

console.log(`\n✔ ${environment} deployed
  mock services  ${mockUrl}
  agent API      ${agentUrl}
  test UI        ${uiUrl}`);

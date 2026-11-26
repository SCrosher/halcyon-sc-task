/** Helpers shared by the setup, dev and deploy scripts. Node built-ins only. */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { connect } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const IS_WINDOWS = process.platform === "win32";
export const PYTHON_PROJECTS = ["mock-services", "agent-api"];
export const NODE_PROJECTS = ["mock-services", "agent-api", "dev/d1-local", "test-ui"];

export function fail(message) {
  console.error(`\n✖ ${message}`);
  process.exit(1);
}

// ---- env files ----------------------------------------------------------------------------------

/** Filled in by the deploy script on first use; everything else in a deploy env file is yours to provide. */
export const GENERATED_KEYS = ["CLOUDFLARE_ACCOUNT_ID", "MOCK_SERVICES_TOKEN"];
const DEPLOY_KEYS = [
  "ANTHROPIC_API_KEY",
  "AGENT_API_TOKENS",
  "CLOUDFLARE_API_TOKEN",
  "D1_API_TOKEN",
  ...GENERATED_KEYS,
];

/** The keys each env file holds. */
export const ENV_FILES = {
  local: { file: ".env", keys: ["ANTHROPIC_API_KEY", "AGENT_API_TOKENS"] },
  staging: { file: ".env.staging", keys: DEPLOY_KEYS },
  production: { file: ".env.production", keys: DEPLOY_KEYS },
};

export function envPath(environment) {
  return join(ROOT, ENV_FILES[environment].file);
}

const LINE = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/;

/** Parse a KEY=VALUE env file (blank and # lines ignored). Missing file = {}. */
export function loadEnvFile(file) {
  const values = {};
  if (!existsSync(file)) return values;
  for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
    if (line.trimStart().startsWith("#")) continue;
    const match = line.match(LINE);
    if (match) values[match[1]] = match[2].replace(/^(['"])(.*)\1$/, "$2");
  }
  return values;
}

/** The first token of a comma-separated AGENT_API_TOKENS value ("" if none). */
export function firstToken(tokens) {
  return (tokens ?? "").split(",")[0].trim();
}

/** Set one key in an env file, keeping every other line as it is. */
export function setEnvValue(file, key, value) {
  const lines = existsSync(file) ? readFileSync(file, "utf8").split(/\r?\n/) : [];
  if (lines.at(-1) === "") lines.pop();
  const index = lines.findIndex((line) => line.match(LINE)?.[1] === key);
  if (index === -1) lines.push(`${key}=${value}`);
  else lines[index] = `${key}=${value}`;
  writeFileSync(file, lines.join("\n") + "\n");
}

/** Create the environment's env file if needed and add any missing keys (empty). Never changes values. */
export function ensureEnvFile(environment) {
  const file = envPath(environment);
  const existing = loadEnvFile(file);
  for (const key of ENV_FILES[environment].keys) if (!(key in existing)) setEnvValue(file, key, "");
  return file;
}

/** Run a command to completion, inheriting output; exits the script if it fails. */
export function run(command, args, { cwd = ROOT, env = process.env, capture = false } = {}) {
  const result = spawnSync(command, args, {
    cwd,
    env,
    stdio: capture ? ["ignore", "pipe", "inherit"] : ["ignore", "inherit", "inherit"],
    encoding: "utf8",
  });
  if (result.error) fail(`${command} failed to start: ${result.error.message}`);
  if (result.status !== 0) fail(`${[command, ...args].join(" ")} exited with ${result.status} (in ${cwd})`);
  return result.stdout ?? "";
}

/** npm is a .cmd shim on Windows, which Node only runs through a shell; callers pass fixed arguments. */
export function npm(args, { cwd = ROOT, env = process.env } = {}) {
  const result = spawnSync(`npm ${args.join(" ")}`, { cwd, env, stdio: ["ignore", "inherit", "inherit"], shell: true });
  if (result.status !== 0) fail(`npm ${args.join(" ")} failed (in ${cwd})`);
}

export function wranglerBin(project) {
  const bin = join(ROOT, project, "node_modules", "wrangler", "bin", "wrangler.js");
  if (!existsSync(bin)) fail(`wrangler is not installed in ${project}. Run: npm run setup`);
  return bin;
}

export function wrangler(project, args, options = {}) {
  return run(process.execPath, [wranglerBin(project), ...args], { cwd: join(ROOT, project), ...options });
}

export function venvPython(project) {
  return join(ROOT, project, ".venv", IS_WINDOWS ? "Scripts" : "bin", IS_WINDOWS ? "python.exe" : "python");
}

/** True if anything accepts connections on the port (IPv4 or IPv6 loopback). */
export async function portInUse(port) {
  const probe = (host) =>
    new Promise((resolvePromise) => {
      const socket = connect({ host, port });
      socket.setTimeout(500);
      socket.once("connect", () => (socket.destroy(), resolvePromise(true)));
      socket.once("timeout", () => (socket.destroy(), resolvePromise(false)));
      socket.once("error", () => resolvePromise(false));
    });
  return (await probe("127.0.0.1")) || (await probe("::1"));
}

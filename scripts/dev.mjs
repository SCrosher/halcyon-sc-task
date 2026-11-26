#!/usr/bin/env node
/**
 * Run everything locally with one command:
 *
 *   npm run dev        local D1 (:8711) -> mock services (:8100) -> agent API (:8000) -> test UI (:5173)
 *   npm run dev:api    the same without the test UI (e.g. when running the UI separately)
 *   npm run db:reset   delete all local data (re-created, empty, on the next `npm run dev`)
 *
 * Local data lives in .local/d1 (wrangler's local D1, gitignored). Nothing here touches
 * Cloudflare: the services run with HALCYON_ENV=local, which always uses the local D1 server.
 * Ctrl+C stops everything; if any process exits, the rest are stopped too.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import {
  IS_WINDOWS,
  NODE_PROJECTS,
  PYTHON_PROJECTS,
  ROOT,
  fail,
  firstToken,
  loadEnvFile,
  portInUse,
  venvPython,
  wrangler,
  wranglerBin,
} from "./lib.mjs";

const LOCAL_D1_DIR = join(ROOT, ".local", "d1");
const D1_PROJECT = "dev/d1-local";
const LOCAL_DATABASES = ["halcyon-mock-services-local", "halcyon-agent-local"];
const STARTUP_TIMEOUT_MS = 90_000;
const COLOURS = { d1: 35, mock: 36, agent: 33, ui: 32 };

const SERVICES = [
  {
    name: "d1",
    port: 8711,
    health: "http://127.0.0.1:8711/health",
    command: process.execPath,
    args: () => [wranglerBin(D1_PROJECT), "dev", "--persist-to", LOCAL_D1_DIR],
    cwd: join(ROOT, D1_PROJECT),
  },
  {
    name: "mock",
    port: 8100,
    health: "http://127.0.0.1:8100/health",
    command: venvPython("mock-services"),
    args: () => ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8100", "--reload"],
    cwd: join(ROOT, "mock-services"),
  },
  {
    name: "agent",
    port: 8000,
    health: "http://127.0.0.1:8000/health",
    command: venvPython("agent-api"),
    args: () => ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
    cwd: join(ROOT, "agent-api"),
  },
  {
    name: "ui",
    port: 5173,
    health: "http://127.0.0.1:5173/",
    // npm is a .cmd shim on Windows, so it has to go through a shell; these arguments are fixed.
    command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
    shell: true,
    args: () => [],
    cwd: join(ROOT, "test-ui"),
  },
];

const WITHOUT_UI = process.argv.includes("--no-ui");
const RUNNING = SERVICES.filter((s) => !(WITHOUT_UI && s.name === "ui"));

// Falls back to the agent API's built-in local token when AGENT_API_TOKENS isn't set.
const LOCAL_TOKEN = firstToken(loadEnvFile(join(ROOT, ".env")).AGENT_API_TOKENS) || "local-dev-token";

// HALCYON_ENV=local is what keeps the services on local data.
const childEnv = {
  ...process.env,
  HALCYON_ENV: "local",
  MOCK_SERVICES_URL: "http://127.0.0.1:8100",
  VITE_AGENT_API_URL: "http://127.0.0.1:8000",
  VITE_AGENT_API_TOKEN: LOCAL_TOKEN,
  PYTHONUNBUFFERED: "1",
  FORCE_COLOR: "1",
};

// ---- preflight --------------------------------------------------------------------------------

async function preflight() {
  for (const project of PYTHON_PROJECTS) {
    if (!existsSync(venvPython(project))) fail(`${project} has no virtualenv. Run: npm run setup`);
  }
  for (const project of NODE_PROJECTS) {
    if (existsSync(join(ROOT, project, "package.json")) && !existsSync(join(ROOT, project, "node_modules"))) {
      fail(`${project} has no node_modules. Run: npm run setup`);
    }
  }
  if (!WITHOUT_UI && !existsSync(join(ROOT, "test-ui", "package.json"))) fail("test-ui/package.json not found.");
  if (!loadEnvFile(join(ROOT, ".env")).ANTHROPIC_API_KEY && !process.env.ANTHROPIC_API_KEY) {
    fail("ANTHROPIC_API_KEY is not set in .env.");
  }
  const busy = [];
  for (const service of RUNNING) if (await portInUse(service.port)) busy.push(`${service.port} (${service.name})`);
  if (busy.length) fail(`Port(s) already in use: ${busy.join(", ")}. Stop whatever is using them and retry.`);
}

// ---- process management -------------------------------------------------------------------------

const children = [];
let stopping = false;

function label(name) {
  return `\x1b[${COLOURS[name]}m${name.padEnd(5)}\x1b[0m│ `;
}

function pipe(stream, name) {
  let buffer = "";
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => {
    buffer += chunk;
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop();
    for (const line of lines) process.stdout.write(label(name) + line + "\n");
  });
}

function start(service) {
  const child = spawn(service.command, service.args(), {
    cwd: service.cwd,
    env: childEnv,
    shell: service.shell ?? false,
    stdio: ["ignore", "pipe", "pipe"],
    detached: !IS_WINDOWS, // own process group on POSIX, so the whole tree can be signalled
    windowsHide: true,
  });
  pipe(child.stdout, service.name);
  pipe(child.stderr, service.name);
  child.on("exit", (code, signal) => {
    child.exited = true;
    if (!stopping) shutdown(1, `${service.name} exited (${signal ?? `code ${code}`}); stopping everything.`);
  });
  children.push(child);
  return child;
}

const STARTED_AT = new Date();

/**
 * Windows has no process groups, and a uvicorn reload worker outlives its parent if the parent dies
 * first. So stop every process created since this script started that is either in a child's
 * process family (followed through parent links, which survive an intermediate process exiting) or
 * still listening on one of our ports - preflight checked they were free, so those are ours too.
 */
function stopWindowsProcesses() {
  const pids = children.map((c) => c.pid).filter(Number.isInteger);
  const ports = RUNNING.map((s) => s.port).join(",");
  const script = [
    "$ErrorActionPreference = 'SilentlyContinue'",
    `$since = [datetime]::Parse('${STARTED_AT.toISOString()}').ToLocalTime().AddSeconds(-1)`,
    "$recent = @(Get-CimInstance Win32_Process | Where-Object { $_.CreationDate -ge $since })",
    `$roots = @(${pids.join(",") || "@()"}) + @(Get-NetTCPConnection -State Listen -LocalPort ${ports} | ForEach-Object OwningProcess)`,
    "$queue = [System.Collections.Queue]::new(); $roots | ForEach-Object { $queue.Enqueue([int]$_) }",
    "$family = @{}",
    "while ($queue.Count) { $id = $queue.Dequeue(); if (-not $family.ContainsKey($id)) { $family[$id] = 1; $recent | Where-Object ParentProcessId -eq $id | ForEach-Object { $queue.Enqueue([int]$_.ProcessId) } } }",
    "$recent | Where-Object { $family.ContainsKey([int]$_.ProcessId) -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
  ].join("\n");
  spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], { stdio: "ignore" });
}

function stopAll() {
  if (IS_WINDOWS) return stopWindowsProcesses();
  for (const child of children) {
    try {
      process.kill(-child.pid, "SIGTERM"); // the whole process group, including reload workers
    } catch {
      // already gone
    }
  }
}

function shutdown(code, message) {
  if (stopping) return;
  stopping = true;
  if (message) console.error(`\n✖ ${message}`);
  stopAll();
  process.exit(code);
}

async function waitHealthy(service, child) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.exited) return shutdown(1, `${service.name} exited during startup (see its output above).`);
    try {
      const response = await fetch(service.health, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  shutdown(1, `${service.name} did not become healthy within ${STARTUP_TIMEOUT_MS / 1000}s.`);
}

// ---- commands -----------------------------------------------------------------------------------

async function reset() {
  if (await portInUse(8711)) fail("The local D1 server is running. Stop `npm run dev` first.");
  rmSync(LOCAL_D1_DIR, { recursive: true, force: true });
  console.log("✔ Local data deleted. `npm run dev` will re-create empty databases.");
}

async function dev() {
  await preflight();

  console.log("→ Applying local migrations");
  for (const database of LOCAL_DATABASES) {
    wrangler(D1_PROJECT, ["d1", "migrations", "apply", database, "--local", "--persist-to", LOCAL_D1_DIR], {
      env: childEnv,
      capture: true,
    });
  }

  process.on("SIGINT", () => shutdown(0));
  process.on("SIGTERM", () => shutdown(0));
  process.on("uncaughtException", (error) => {
    console.error(error);
    shutdown(1);
  });

  for (const service of RUNNING) {
    console.log(`→ Starting ${service.name} on :${service.port}`);
    await waitHealthy(service, start(service));
  }

  const lines = [
    "✔ Halcyon is running locally (Ctrl+C to stop)",
    WITHOUT_UI ? null : "  test UI        http://127.0.0.1:5173",
    `  agent API      http://127.0.0.1:8000   bearer token: ${LOCAL_TOKEN}`,
    "  mock services  http://127.0.0.1:8100",
    "  local D1       http://127.0.0.1:8711   data in .local/d1 (npm run db:reset to clear)",
  ];
  console.log(`\n${lines.filter(Boolean).join("\n")}\n`);
}

if (process.argv[2] === "reset") await reset();
else await dev();

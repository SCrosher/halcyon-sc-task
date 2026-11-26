#!/usr/bin/env node
/**
 * One-time (and safe to re-run) local setup:
 *   - a Python 3.12+ virtualenv per Python project, with its dependencies
 *   - npm dependencies for every Node project
 *   - .env, .env.staging and .env.production with every key they need (existing values are never changed)
 *
 *   npm run setup
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, relative } from "node:path";
import {
  ENV_FILES,
  GENERATED_KEYS,
  IS_WINDOWS,
  NODE_PROJECTS,
  PYTHON_PROJECTS,
  ROOT,
  ensureEnvFile,
  fail,
  loadEnvFile,
  npm,
  run,
  venvPython,
} from "./lib.mjs";

const MIN_PYTHON = [3, 12];

function pythonCandidates() {
  if (!IS_WINDOWS) return [["python3.13"], ["python3.12"], ["python3"], ["python"]];
  const local = process.env.LOCALAPPDATA ?? "";
  return [
    ["py", "-3.13"],
    ["py", "-3.12"],
    ["python"],
    [join(local, "Programs", "Python", "Python313", "python.exe")],
    [join(local, "Programs", "Python", "Python312", "python.exe")],
  ];
}

function findPython() {
  for (const [command, ...args] of pythonCandidates()) {
    const result = spawnSync(command, [...args, "-c", "import sys; print(*sys.version_info[:2])"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    if (result.status !== 0 || !result.stdout) continue;
    const [major, minor] = result.stdout.trim().split(" ").map(Number);
    if (major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])) {
      return { command, args, version: `${major}.${minor}` };
    }
  }
  fail(`Python ${MIN_PYTHON.join(".")}+ not found. Install it (e.g. winget install Python.Python.3.13) and re-run.`);
}

const python = findPython();
console.log(`Using Python ${python.version} (${[python.command, ...python.args].join(" ")})`);

for (const project of PYTHON_PROJECTS) {
  const cwd = join(ROOT, project);
  if (!existsSync(venvPython(project))) {
    console.log(`\n→ ${project}: creating .venv`);
    run(python.command, [...python.args, "-m", "venv", ".venv"], { cwd });
  }
  console.log(`\n→ ${project}: installing Python dependencies`);
  run(venvPython(project), ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-e", ".[dev]"], { cwd });
}

console.log("\n→ repo root: installing npm dependencies (lint and format tooling)");
npm(["install", "--no-fund", "--no-audit"], { cwd: ROOT });

for (const project of NODE_PROJECTS) {
  if (!existsSync(join(ROOT, project, "package.json"))) continue;
  console.log(`\n→ ${project}: installing npm dependencies`);
  npm(["install", "--no-fund", "--no-audit"], { cwd: join(ROOT, project) });
}

console.log("\n→ Env files");
for (const environment of Object.keys(ENV_FILES)) {
  const file = ensureEnvFile(environment);
  const values = loadEnvFile(file);
  const empty = ENV_FILES[environment].keys.filter((k) => !values[k] && !GENERATED_KEYS.includes(k));
  const optional = environment === "local" ? ["AGENT_API_TOKENS"] : [];
  const needed = empty.filter((k) => !optional.includes(k));
  console.log(`  ${relative(ROOT, file).padEnd(16)} ${needed.length ? `fill in: ${needed.join(", ")}` : "ready"}`);
}
console.log("\n✔ Setup complete. Start everything with: npm run dev");

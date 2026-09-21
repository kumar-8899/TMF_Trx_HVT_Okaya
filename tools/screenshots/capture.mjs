#!/usr/bin/env node
// DEV-ONLY screenshot capture pipeline for the in-app manual + developer guide.
//
//   cd tools/screenshots && npm install && npm run capture
//   node capture.mjs --only dashboard,recipes      # refresh a subset (other manifest entries kept)
//
// Drives the already-installed Microsoft Edge through playwright-core (no browser download),
// against the BUILT SPA served single-origin by `python station.py --no-window` on :8000.
// Writes docs/assets/screens/<id>.png and merges docs/assets/manifest.json. See README.md.

import { chromium } from "playwright-core";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const OUT_DIR = path.join(ROOT, "docs", "assets", "screens");
const MANIFEST = path.join(ROOT, "docs", "assets", "manifest.json");
const HOST = "127.0.0.1";
const PORT = 8000;
const BASE = `http://${HOST}:${PORT}`;
const ADMIN_USER = process.env.TMF_SCREENSHOT_USER || "admin";
const ADMIN_PASS = process.env.TMF_SCREENSHOT_PASSWORD || "admin"; // dev credential only
const MAX_FILE_KB = 250;
const MAX_TOTAL_MB = 4;
const FREEZE_CSS =
  "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}";

// ---------------------------------------------------------------------------- args
function parseArgs(argv) {
  const a = { only: null, viewport: "1440x900", seed: true, help: false, reuse: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--only") a.only = (argv[++i] || "").split(",").map((s) => s.trim()).filter(Boolean);
    else if (k.startsWith("--only=")) a.only = k.slice(7).split(",").map((s) => s.trim()).filter(Boolean);
    else if (k === "--viewport") a.viewport = argv[++i];
    else if (k.startsWith("--viewport=")) a.viewport = k.slice(11);
    else if (k === "--no-seed") a.seed = false;
    else if (k === "--reuse-running") a.reuse = true;
    else if (k === "-h" || k === "--help") a.help = true;
    else die(`unknown argument '${k}' (see --help)`);
  }
  return a;
}

class Fatal extends Error {
  constructor(msg, code = 1) { super(msg); this.exitCode = code; }
}
// Throws (never process.exit) so main()'s `finally` still stops a station this script started.
function die(msg, code = 1) {
  throw new Fatal(msg, code);
}
const log = (m) => console.log(`capture: ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------- helpers
function frameworkVersion() {
  const src = fs.readFileSync(path.join(ROOT, "backend", "core", "__init__.py"), "utf8");
  const m = src.match(/^__version__\s*=\s*["']([^"']+)["']/m);
  if (!m) die("could not parse __version__ from backend/core/__init__.py");
  return m[1];
}

/** EXACTLY catalog.source_hash (backend/modules/help/catalog.py): sha256 of the bytes with every
 *  CRLF replaced by LF, first 16 hex chars. latin1 round-trips arbitrary bytes 1:1. */
function sourceHash(file) {
  const buf = fs.readFileSync(file);
  const norm = Buffer.from(buf.toString("latin1").replace(/\r\n/g, "\n"), "latin1");
  return createHash("sha256").update(norm).digest("hex").slice(0, 16);
}

async function healthOk() {
  try {
    const r = await fetch(`${BASE}/healthz`, { signal: AbortSignal.timeout(2500) });
    return r.status === 200;
  } catch {
    return false;
  }
}

function portInUse(port = PORT) {
  return new Promise((resolve) => {
    const s = net.connect({ host: HOST, port });
    s.once("connect", () => { s.destroy(); resolve(true); });
    s.once("error", () => resolve(false));
    s.setTimeout(1500, () => { s.destroy(); resolve(false); });
  });
}

async function waitFor(pred, timeoutMs, label, everyMs = 1000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (await pred()) return true;
    await sleep(everyMs);
  }
  log(`timed out waiting for ${label}`);
  return false;
}

async function login() {
  const r = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: ADMIN_USER, credential: { password: ADMIN_PASS } }),
  });
  const body = await r.json().catch(() => null);
  if (r.status !== 200 || !body?.token) die(`login as '${ADMIN_USER}' failed (HTTP ${r.status}): ${JSON.stringify(body)}`);
  if (body.principal?.must_change_password)
    die(`'${ADMIN_USER}' must change its password first - the SPA would redirect every page to /change-password`);
  return body.token;
}

// ---------------------------------------------------------------------------- server lifecycle
const server = { proc: null, started: false, logFile: path.join(os.tmpdir(), "tmf-screenshots-station.log") };

function ensureFrontendBuilt() {
  if (fs.existsSync(path.join(ROOT, "frontend", "dist", "index.html"))) return;
  log("frontend/dist missing - running `npm run build` in frontend/ ...");
  const r = spawnSync("npm", ["run", "build"], { cwd: path.join(ROOT, "frontend"), stdio: "inherit", shell: true });
  if (r.status !== 0) die("frontend build failed (cd frontend && npm install && npm run build)");
}

async function startServer(reuse) {
  const occupied = (await healthOk()) || (await portInUse());
  if (occupied) {
    if (!reuse) {
      die(
        `something is already listening on :${PORT}. The shared docs images must come from a PRISTINE station ` +
          "(fresh state, example config) - a running station would leak its own branding, instruments and logs " +
          "into them. Stop it and retry (or pass --reuse-running for a throw-away experiment; never commit that output).",
      );
    }
    log(`WARNING --reuse-running: capturing whatever is on :${PORT}; do NOT commit these images`);
    if (!(await healthOk()) && !(await waitFor(healthOk, 30000, "existing service on :8000"))) {
      die(`port ${PORT} is occupied by something that is not a healthy station`);
    }
    return;
  }
  ensureFrontendBuilt();
  const py = process.env.PYTHON || "python";
  const stateDir = path.join(os.tmpdir(), "tmf-screenshots-state");
  const fd = fs.openSync(server.logFile, "w");
  log(`starting a pristine station (state: ${stateDir}, log: ${server.logFile})`);
  server.proc = spawn(py, [path.join(HERE, "run_isolated.py"), stateDir], {
    cwd: ROOT, stdio: ["ignore", fd, fd], windowsHide: true,
  });
  server.started = true;
  let exited = false;
  server.proc.on("exit", (c) => { exited = true; log(`station exited (code ${c})`); });
  const ok = await waitFor(async () => (exited ? true : await healthOk()), 240000, "the station to come up");
  if (exited || !ok) {
    const tail = fs.readFileSync(server.logFile, "utf8").split("\n").slice(-25).join("\n");
    await stopServer();
    die(`station did not come up. Last log lines:\n${tail}`);
  }
  log("station is up");
}

function killTree(pid) {
  // Windows: kill the whole tree (station.py -> launcher -> backend/broker/vite children).
  if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
  else try { process.kill(-pid, "SIGKILL"); } catch { /* already gone */ }
}

const stub = { proc: null };

/** The framework's reference LabVIEW stub (backend/tools/lv_stub.py) answers as station st1, so the
 *  pristine station reads "ready" (bridge online) instead of a red "bridge offline" banner. It needs
 *  a broker on :1883; without one the dashboard honestly shows the offline state. */
async function startStub() {
  if (!(await portInUse(1883))) {
    log("WARNING: no MQTT broker on :1883 - the dashboard will show 'bridge offline' (start Mosquitto for a healthy-looking station)");
    return;
  }
  const py = process.env.PYTHON || "python";
  stub.proc = spawn(py, ["-m", "tools.lv_stub", "--station", "st1"], {
    cwd: path.join(ROOT, "backend"), stdio: "ignore", windowsHide: true,
  });
  log("started the reference LabVIEW stub (station st1) so the station reads 'ready'");
  const ready = async () => {
    try { return (await fetch(`${BASE}/readyz`, { signal: AbortSignal.timeout(2500) })).status === 200; } catch { return false; }
  };
  if (!(await waitFor(ready, 45000, "the station to report ready"))) log("WARNING: station never reported ready - dashboard may show a degraded state");
  await sleep(2000);
}

function stopStub() {
  if (!stub.proc) return;
  killTree(stub.proc.pid);
  stub.proc = null;
}

async function stopServer(token) {
  if (!server.started || !server.proc) return;
  const proc = server.proc;
  server.proc = null;
  const alive = () => proc.exitCode === null && proc.signalCode === null;
  if (alive() && token) {
    // Graceful: the UI's "Shut down station" path (controller -> safe state, then exit 0).
    try {
      await fetch(`${BASE}/system/shutdown`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      const end = Date.now() + 30000;
      while (alive() && Date.now() < end) await sleep(500);
    } catch { /* fall through to the hard stop */ }
  }
  if (alive()) { log("station did not exit gracefully - killing its process tree"); killTree(proc.pid); await sleep(1500); }
  log("station stopped");
}

async function seed(token) {
  if (process.argv.includes("--no-seed")) { log("--no-seed: skipping seed"); return null; }
  const py = process.env.PYTHON || "python";
  const r = spawnSync(py, [path.join(HERE, "seed.py"), "--base", BASE, "--user", ADMIN_USER, "--password", ADMIN_PASS],
    { encoding: "utf8" });
  process.stderr.write(r.stderr || "");
  if (r.status !== 0) die("seed.py failed (see above)");
  let summary = null;
  try { summary = JSON.parse((r.stdout || "").trim().split("\n").pop()); } catch { /* handled below */ }
  if (!summary) die(`seed.py printed no summary: ${r.stdout}`);
  for (const s of summary.skipped || []) log(`seed skipped: ${s}`);
  if (summary.needs_restart) {
    if (server.started) {
      log("seeded Python instruments -> relaunching the backend so they build (POST /system/relaunch)");
      await fetch(`${BASE}/system/relaunch`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      await waitFor(async () => !(await healthOk()), 20000, "backend to go down", 500);
      if (!(await waitFor(healthOk, 120000, "backend to come back up"))) die("backend did not come back after relaunch");
      await sleep(4000); // let modules + the variable engine finish binding
    } else {
      log("NOTE: seeded instruments will only show live state after the (reused) backend is restarted");
    }
  }
  return summary;
}

// ---------------------------------------------------------------------------- capture
async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log("usage: node capture.mjs [--only id1,id2] [--viewport 1440x900] [--no-seed] [--reuse-running]");
    return;
  }
  const m = /^(\d+)x(\d+)$/.exec(args.viewport || "");
  if (!m) die(`--viewport must look like 1440x900, got '${args.viewport}'`);
  const viewport = { width: +m[1], height: +m[2] };

  const routes = JSON.parse(fs.readFileSync(path.join(HERE, "routes.json"), "utf8"));
  const known = new Set(routes.map((r) => r.id));
  let todo = routes;
  if (args.only) {
    const bad = args.only.filter((id) => !known.has(id));
    if (bad.length) die(`unknown route id(s) in --only: ${bad.join(", ")} (known: ${[...known].join(", ")})`);
    todo = routes.filter((r) => args.only.includes(r.id));
  }
  // Fail early on a stale routes.json (a screen file that moved) - never silently emit a bad hash.
  for (const r of todo) {
    if (!fs.existsSync(path.join(ROOT, r.screen_source))) die(`route '${r.id}': screen_source '${r.screen_source}' does not exist`);
  }

  const version = frameworkVersion();
  let browser = null;
  let token = null;
  const results = [];
  let exitCode = 0;
  const onSig = async () => { await stopServer(token); process.exit(130); };
  process.on("SIGINT", onSig);
  process.on("SIGTERM", onSig);

  try {
    // Edge first: fail before starting any server if the browser is missing.
    try {
      browser = await chromium.launch({ channel: "msedge", headless: true });
    } catch (e) {
      die(
        "could not launch Microsoft Edge via playwright-core (channel 'msedge'). Install Edge " +
          "(it ships with Windows 10/11) and retry. This pipeline never downloads a browser and " +
          `never skips silently.\n  underlying error: ${String(e.message || e).split("\n")[0]}`,
        2,
      );
    }

    await startServer(args.reuse);
    if (server.started) await startStub();
    token = await login();
    await seed(token);
    token = await login(); // fresh token: a relaunch may have reset sessions

    const context = await browser.newContext({
      viewport, deviceScaleFactor: 1, colorScheme: "light", reducedMotion: "reduce", locale: "en-US",
    });
    await context.addInitScript(
      ([tok]) => {
        try {
          localStorage.setItem("tmf.token", tok);
          localStorage.setItem("tmf.colormode", "light");
        } catch { /* storage unavailable */ }
      },
      [token],
    );
    fs.mkdirSync(OUT_DIR, { recursive: true });

    for (const r of todo) {
      const page = await context.newPage();
      const pageErrors = [];
      page.on("pageerror", (e) => pageErrors.push(String(e.message || e).split("\n")[0]));
      const rec = { id: r.id, ok: false, note: "" };
      try {
        await page.goto(BASE + r.route, { waitUntil: "domcontentloaded", timeout: 30000 });
        await page.addStyleTag({ content: FREEZE_CSS });
        await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {}); // WS/polling pages may never idle
        if (new URL(page.url()).pathname.startsWith("/login")) throw new Error("redirected to /login (auth failed)");
        if (new URL(page.url()).pathname.startsWith("/change-password")) throw new Error("redirected to /change-password");
        await page
          .locator("main")
          .getByText(r.wait_for, { exact: false })
          .first()
          .waitFor({ state: "visible", timeout: 15000 })
          .catch(() => { throw new Error(`text '${r.wait_for}' never appeared in <main> (page: ${page.url()})`); });
        await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
        await page.addStyleTag({ content: FREEZE_CSS });
        await page.evaluate(() => { document.activeElement?.blur?.(); window.scrollTo(0, 0); });
        await page.mouse.move(0, 0);
        await sleep(900); // settle: late fetches, chart layout, skeleton -> content
        const file = path.join(OUT_DIR, `${r.id}.png`);
        await page.screenshot({ path: file, type: "png", fullPage: false, omitBackground: false });
        rec.ok = true;
        rec.bytes = fs.statSync(file).size;
        if (pageErrors.length) rec.note = `page errors: ${pageErrors.slice(0, 2).join(" | ")}`;
      } catch (e) {
        rec.note = String(e.message || e).split("\n")[0];
        exitCode = 1;
      } finally {
        await page.close();
      }
      results.push(rec);
      log(`${rec.ok ? "ok  " : "FAIL"} ${r.id}${rec.ok ? ` (${(rec.bytes / 1024).toFixed(0)} KB)` : ""}${rec.note ? ` - ${rec.note}` : ""}`);
    }
    await context.close();
  } finally {
    await browser?.close().catch(() => {});
    await stopServer(token);
  }

  // ---- manifest: refresh captured entries in place, keep everything else
  const okIds = new Set(results.filter((r) => r.ok).map((r) => r.id));
  let manifest = { schema_version: 1, images: [] };
  if (fs.existsSync(MANIFEST)) {
    try { manifest = JSON.parse(fs.readFileSync(MANIFEST, "utf8")); } catch (e) { die(`existing manifest.json is not valid JSON: ${e.message}`); }
    if (!Array.isArray(manifest.images)) manifest.images = [];
  }
  const byId = new Map(manifest.images.map((e) => [e.id, e]));
  for (const r of todo) {
    if (!okIds.has(r.id)) continue;
    byId.set(r.id, {
      id: r.id,
      file: `screens/${r.id}.png`,
      alt: r.alt,
      audience: r.audience,
      route: r.route,
      framework_version: version,
      source: r.screen_source,
      source_hash: sourceHash(path.join(ROOT, r.screen_source)),
    });
  }
  const images = [...byId.values()].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  fs.mkdirSync(path.dirname(MANIFEST), { recursive: true });
  fs.writeFileSync(MANIFEST, JSON.stringify({ schema_version: 1, images }, null, 2) + "\n", { encoding: "utf8" });

  // ---- size report
  let total = 0;
  for (const e of images) {
    const f = path.join(ROOT, "docs", "assets", e.file);
    if (!fs.existsSync(f)) { log(`WARNING: manifest entry '${e.id}' points at a missing file ${e.file}`); continue; }
    const kb = fs.statSync(f).size / 1024;
    total += kb;
    if (kb > MAX_FILE_KB) log(`WARNING: ${e.file} is ${kb.toFixed(0)} KB (> ${MAX_FILE_KB} KB) - consider --viewport 1280x800`);
  }
  log(`${okIds.size}/${todo.length} captured; manifest has ${images.length} image(s); total ${(total / 1024).toFixed(2)} MB`);
  if (total / 1024 > MAX_TOTAL_MB) log(`WARNING: set exceeds ${MAX_TOTAL_MB} MB - consider --viewport 1280x800`);
  const failed = results.filter((r) => !r.ok);
  if (failed.length) {
    log(`FAILED: ${failed.map((f) => f.id).join(", ")}`);
    exitCode = 1;
  }
  process.exit(exitCode);
}

main().catch((e) => {
  if (e instanceof Fatal) console.error(`capture: ERROR: ${e.message}`);
  else console.error(e);
  process.exit(e?.exitCode ?? 1);
});

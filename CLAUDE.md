# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**Super_Test_App is the framework repo** for a multi-station Test & Measurement platform — not an application. Applications fork a **release tag** (never `main`) and stay downstream; see `docs/TEMPLATE.md` for the ownership boundary. Version lives in `backend/core/__init__.py` + `backend/pyproject.toml`; every release is a git tag `v<version>` recorded in `CHANGELOG.md`.

**The docs are the contract.** Decide → update the doc → build against the doc, never from memory. Start with `docs/ARCHITECTURE.md` (current-state map), `docs/PRINCIPLES.md` (locked decisions), then the per-module contracts in `docs/contracts/`. On any feature change, also update the in-app help (`docs/help/user/` for operators, `docs/help/dev/` for super_admin) and `backend/modules/help/catalog.py` if pages are added/moved.

## Commands

```pwsh
# Whole stack: mosquitto (:1883) + backend (:8000) + Vite (:5173) + opens login page
powershell -ExecutionPolicy Bypass -File .\dev.ps1

# One-click: backend serves the built SPA on :8000 in a native pywebview window (docs/RUNNING.md)
python station.py                        # --dev (Vite+HMR) | --browser | --fullscreen | --no-window

# Backend
cd backend
python -m pip install -e ".[dev]"
pytest -q                                # full suite (tests/ + modules/ + debug_server/ + instrumentlib/)
pytest modules/recipe -q                 # one module's tests
pytest tests/test_core_db.py::test_name  # single test
python run.py                            # serve http://127.0.0.1:8000 (GET /healthz, /readyz)
python launcher.py                       # run.py wrapper: exit 42 → restart ("Relaunch to apply")
python run_debug_server.py               # debug sidecar: MQTT timeline UI on :8001 (REMOTE_DEBUG.md)
python -m tools.config_doctor            # dry-run config drift (add --apply to reconcile)
ruff check .                             # lint (line-length 100, py311)

# Frontend
cd frontend
npm install
npm run dev                              # Vite :5173 (proxy → :8000)
npx vitest run                           # tests
npm run build                            # tsc + vite build (this is the type check)

# Python controller (standalone; normally the backend auto-starts it)
cd controller
python -m pip install -e .
python -m controller controller.json
python -m pytest -q                      # live-broker tests skip if no broker on :1883
```

Live config `backend/config/app.json` / `license.json` is gitignored — copy from the `*.example.json` on first run. Dev login `admin` / `admin`. Mosquitto is expected at `D:\tools\mosquitto\mosquitto.exe` (dev.ps1) or vendored under `deploy/vendor/mosquitto/`.

## Architecture

Three tiers, two seams:

```
Controller  ◄── MQTT only (tmf/{station}/…) ──►  Python backend  ◄── HTTP+WS ──►  React frontend
```

- **Controller** owns test execution: sequence, step timing, abort/timeout, safety, hardware. It is a **contract with two implementations** — the LabVIEW engine (`labview/`) or the standalone Python controller (`controller/`, imports nothing from `backend/`). The app cannot tell them apart. Exactly one is active per PC, selected by `app.json` `controller.kind`; when `"python"`, the backend supervises it (start/stop with the app).
- **Python backend** (`backend/`) is the app platform and the **only web edge**. `core/` = module framework (registry, autodiscovery, manifests, activation gate) + services injected via CoreServices DI: `db` (SQLite, RAG envelope), `bridge` (MQTT client), `config` (JSON + JSONSchema), `diagnostics`, `auth` port, `web` (FastAPI, RFC-7807, `require_permission`), `streaming` (StreamHub). `run.py` boots uvicorn on a Windows **selector** event loop (aiomqtt requires it).
- **React frontend** (`frontend/`) talks only to Python (REST + WS), never to the broker. Vite + React + TS + MUI.

**MQTT grammar** (`docs/LABVIEW_BRIDGE.md`): `tmf/{station}/{class}/{name}` with classes cmd/query/stream/value/event/diag/status; request/reply is MQTT-3.1.1-safe via payload `reply_to` + `id`. Topics are rule-derived from this grammar, never stored per-variable. Debugging starts with MQTT Explorer on `tmf/#`, not a stack trace.

**Modules** (`backend/modules/`: runs, auth, logs, recipe, report, mes, health, config, variables, help): each has a `manifest.json`, the lifecycle construct → init → start → stop → health, and is gated by config ∩ license at activation. Modules depend **only on core, never on each other**, and consume **permissions (`DOMAIN.ACTION`), never roles**. Each must run standalone (core + that module); testers live in `modules/*/tester/`.

**Multi-station** (`docs/MULTI_STATION.md`): one PC runs N sockets `st1…stN`; one socket looks single-station.

### Key cross-cutting facts

- **Instrument instances have one source**: the Config → Instruments page (v1.5.0). The variable engine and the supervised controller both consume its records; a `controller.json` `instruments` list is ignored under app supervision (honored only in standalone `python -m controller`). Simulation is the per-instrument `simulated` toggle (v1.5.1) — there is no global sim mode under supervision.
- **Two instrument trees, don't confuse them**: `backend/instrumentlib/` is the framework capability **base/SDK** (`tmf-instrumentlib`, separately versioned, governed by `docs/INSTRUMENT_LIBRARY.md`); repo-root `instrument_libs/` (absent here, present in forks) holds **drivers** an app copied from the central `Instrument_Library` repo — auto-discovered by the variables module (v1.4.1).
- **Recipes are controller-native** (v1.3.0): steps are `{id, type, params}` against the controller's step-type catalog (8 core types + app step-type packages). The legacy 16-type path exists internally but is not surfaced.
- **Screen overrides** (`frontend/src/app/registry.ts`): forks customize Runs/Recipes/recipe-editor/recipe-detail/Maintenance by dropping `*.tsx` into `frontend/src/app/overrides/` (shipped empty here) — never by editing framework `screens/*`.
- **Data is JSON with JSON Schema** and a `schema_version` header; `*.example.json` ships, live file is gitignored. Persisted records carry the RAG envelope (id, type, ts, station, source_version, human-readable summary), append-only where possible.
- **Remote debugging** (`docs/REMOTE_DEBUG.md`): the Debug Server sidecar can record a bench to disk (rolling JSONL + 30 s failure snapshots) and be pulled to a laptop with the repo-root **`tmf-debug`** CLI. Captures + condensed `digest.json` land in **`.debug/`** at the repo root (gitignored) — that is where to look for a bench capture: `tmf-debug why --host <bench> --last-run` writes both there, and `first_fault` in the digest is the highest-value field. On/off is Settings → Remote debugging (`app.json` `debug.enabled`), supervised by `station.py`.
- **Fork ownership boundary** (`docs/TEMPLATE.md` §1): app-owned paths are `app/<name>/` (step-type packages, variable maps, recipes, controller.json), `backend/modules/<app>_*/`, `instrument_libs/`, `frontend/src/app/overrides/`, `labview/App/`, and live config. Everything else is framework-owned — a fork needing a framework change gets it via a framework release, never a downstream patch. When editing this repo you are editing the framework: keep that boundary mergeable.

### Skills

Five skills ship with the framework: `new-test-app` (fork a new app), `system-blueprint` (generate an app's variable map + instrument checklist from a filled System Blueprint spreadsheet — `docs/SYSTEM_BLUEPRINT.md`, tooling in `backend/tools/blueprint/`), `test-step-authoring` (author controller step types), `add-bench-test` (add a test to an existing app), `create-instrument-library` (author a driver). They live BOTH as **project skills** in `.claude/skills/` (auto-loaded when you open the repo in the Claude Code interface/agent mode — the usual path; forks inherit them) AND in a **marketplace plugin** `plugins/tmf-tools/` for the terminal `claude` CLI (`/plugin marketplace add kumar-8899/Super_Test_App` → `/plugin install tmf-tools`). Keep the two copies in sync when editing a skill. Skills are env-driven (`$FRAMEWORK_REMOTE`, `$TMF_INSTRUMENT_LIBRARY`) so they run on any machine. Use them instead of hand-rolling; see `docs/DEVELOPER_ONBOARDING.md`.

## Testing conventions

- Backend: pytest with `asyncio_mode = "auto"`; testpaths cover `tests/`, `modules/`, `debug_server/`, `instrumentlib/`. Integration tests that need a live broker skip cleanly when :1883 is down.
- The user verifies against real LabVIEW + MQTT Explorer — do not write stub/placeholder implementations to fake a passing state.
- Failures must be loud and structured: typed diagnostic events + RFC-7807 bodies, never bare exceptions.

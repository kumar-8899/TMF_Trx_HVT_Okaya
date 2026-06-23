# Test & Measurement Framework

Multi-station T&M software template (runs singleton too).

- **LabVIEW** = controller — owns test execution, sequence, step timing, abort/timeout, safety, hardware (HAL).
- **Python** = app platform + sole web edge — modules, db, web, MQTT bridge client.
- **React frontend** = operator UI, talks only to Python. LabVIEW ↔ Python over **MQTT only**.

## Source of truth — read first
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — current-state map: tiers, modules + status, the MQTT surface, repo layout (start here for the overview).
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md) — rules + locked decisions (the constitution).
- [docs/CORE.md](docs/CORE.md) — Python platform, module framework, activation gate, acceptance (§10).
- [docs/LABVIEW_BRIDGE.md](docs/LABVIEW_BRIDGE.md) — MQTT wire contract + Phase-0 LabVIEW stub (§12).
- [docs/FRONTEND.md](docs/FRONTEND.md) — the React UI: theme, components, screens, auth, streaming.
- [docs/contracts/](docs/contracts/) — per-module contracts (auth, daq, runs, recipe, logs, report, step types).

Build to the docs, not to memory. Decide → update doc → build.

## Layout
```
backend/    Python — platform (core/) + modules (modules/)
labview/    controller + DQMH Bridge module
frontend/   React shell (unchanged)
src-tauri/  Tauri shell + installer
deploy/     mosquitto.conf, CI helpers
docs/       the contracts
```

## Dev quickstart

Whole stack (broker + backend + frontend + opens the login page):
```pwsh
powershell -ExecutionPolicy Bypass -File .\dev.ps1
```

Backend only:
```pwsh
cd backend
python -m pip install -e ".[dev]"
pytest -q                # 235 passing
python run.py            # serves http://127.0.0.1:8000 ; GET /healthz
```

Debug Server (dev-only sidecar — correlated MQTT timeline, [docs/DEBUG_SERVER.md](docs/DEBUG_SERVER.md)):
```pwsh
cd backend
python run_debug_server.py   # subscribes the station bus → UI on http://127.0.0.1:8001
```

Frontend only:
```pwsh
cd frontend
npm install
npm run dev              # Vite on :5173 (proxy → :8000)
npx vitest run           # 27 passing
```

Live config (`config/app.json`, `config/license.json`) is gitignored — copy from
the `*.example.json` on first run. Dev login `admin` / `admin` (super_admin; a DEV
credential — provision properly for production).

When new modules/permissions land, the live config can fall behind the examples
(surfacing as a 403/404). The backend logs a drift warning at boot; reconcile
non-destructively with:
```pwsh
cd backend
python -m tools.config_doctor          # dry-run: show missing modules/roles/perms/licenses
python -m tools.config_doctor --apply  # add them (then restart + re-login)
```

## Phase 0 — walking skeleton (complete)

End to end: core services + module framework + activation gate + MQTT bridge
client + the `hello` reference module + a runnable LabVIEW Bridge stub, all in
CI. See [docs/PHASE0_ACCEPTANCE.md](docs/PHASE0_ACCEPTANCE.md) for the §10
criteria walk and a one-command local demo:

```pwsh
./deploy/run-local.ps1     # broker + app + stub; watch tmf/# in MQTT Explorer
```

One open item remains, on the LabVIEW desk: build the real DQMH Bridge VI per
[labview/bridge/README.md](labview/bridge/README.md) and register a self-hosted
runner. Until then the Python reference stub
([backend/tools/lv_stub.py](backend/tools/lv_stub.py)) stands in as the §12 wire
contract.

## Phase 1 — DAQ / stream + controller vertical (Python half complete)

Core latest-frame cache + StreamHub; the `daq` module (ai/di streaming, WS
relays, variables) and the `runs` module (run control, run records,
`/ws/station` + `/diagnostics/stream`). Command/reply is 3.1.1-safe (payload
`reply_to` + `id`). See [docs/PHASE1_ACCEPTANCE.md](docs/PHASE1_ACCEPTANCE.md);
contracts in [docs/contracts/](docs/contracts/).

Live acceptance is gated on the real LabVIEW DAQ + controller implementing the
LABVIEW_BRIDGE.md §5.1 command catalogue:

```pwsh
cd backend; python -m tools.check_phase1 --no-stub
```

## Phase 2 — business modules (Auth complete, backend)

Permission-first `auth` module (`DOMAIN.ACTION`, one role/user, resolve-at-login,
opaque single-session, Argon2, pluggable authenticator seam, full user management
gated on `AUTH.MANAGE_USERS`). Fills the `core.auth` port; modules consume
permissions via `require_permission`. See
[docs/PHASE2_AUTH_ACCEPTANCE.md](docs/PHASE2_AUTH_ACCEPTANCE.md) and
[docs/contracts/auth.md](docs/contracts/auth.md).

Known gap: the PyInstaller sidecar needs a packaging fix to run frozen
(dynamically-discovered modules + argon2 not yet bundled) — see the acceptance
doc. Auth UI is a later frontend phase.

The `logs` module (Action & Error Logs) is also complete: persists the diag bus
to durable, queryable `error_log` records (single sink + dedup/coalescing) and
attributed `action_log` records, with cursor-paginated query/stats/delete gated on
`DIAGNOSTICS.VIEW`/`DIAGNOSTICS.PURGE` and config-driven retention/pruning. See
[docs/PHASE2_LOGS_ACCEPTANCE.md](docs/PHASE2_LOGS_ACCEPTANCE.md) and
[docs/contracts/LOGS.md](docs/contracts/LOGS.md).

The `recipe` module (Test Recipe) is complete on the Python side (R1–R6): one
recipe shape with 16 pluggable step types (incl. the simplified `parametric_test`
authored by the UI), filesystem versioning (append-only,
content-hashed) + DB corpus mirror, schema + semantic validation, the
`query/recipe.fetch` execution wire with `${run.x}` substitution, ZIP
export/import, and version diff. See
[docs/PHASE2_RECIPE_ACCEPTANCE.md](docs/PHASE2_RECIPE_ACCEPTANCE.md) and
[docs/contracts/RECIPE.md](docs/contracts/RECIPE.md). LabVIEW Test Sequencer
`Execute` VIs are the remaining desk work against the documented contract.

The `report` module (Report / Analytics) is complete: run reports + analytics
(counts / yield / by-recipe), multi-sink output (SQLite + folder, split by
pass/fail), and export. See [docs/contracts/runs.md](docs/contracts/runs.md) and
the Reports screen.

## Frontend — operator UI (complete, this phase)

Full React UI on a navy/green "instrument console" theme (light + dark toggle):
shell + Login/Change-password, Dashboard, DAQ (live channel tiles + sparklines),
Runs (barcode/recipe **Start dialog**, live **test-result** table, run history),
Recipes (scalable list + two-pane editor authoring `parametric_test` tests +
read-only view), Reports, and Users (temp-password creation, role dropdowns,
protected super_admin). See [docs/FRONTEND.md](docs/FRONTEND.md).

Recent overhauls in this phase: the theme re-skin, the Recipe authoring rework,
the Test-Runs flow (acquisition + result rows), and User-management hardening.

Next (deferred): harden Licensing; Variable Engine catalog; phase-2 scalable
step-type sequence editor; PyInstaller frozen-sidecar packaging; the LabVIEW desk
work (real Bridge, DAQ/controller handlers, Sequencer `Execute`, emitting
`test-result`/`run-*` events with the minted `run_id`).

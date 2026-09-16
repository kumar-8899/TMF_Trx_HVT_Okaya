# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**This is an application fork, not the framework.** `TMF_Trx_HVT_Okaya` is the **Okaya HVT
Testbench** — a high-voltage transformer test bench built by forking the `Super_Test_App`
framework at a release tag (`upstream` remote, **push-disabled**) and adding app-owned content
on top (`docs/APP_REPO.md`, `docs/TEMPLATE.md` §1 is the ownership contract). The app's own
version is `app/okaya_hvt/VERSION` (currently `1.0.0`), independent of the framework's version
(`backend/pyproject.toml`, currently `1.22.1`). `CHANGELOG.md` at the repo root is still the
**framework's** changelog (inherited, not app-specific) — don't add app entries there.

This working tree currently has app content (`app/`, `instrument_libs/`,
`frontend/src/app/overrides/okaya_hvt/`) scaffolded but **not yet committed** (`git status`
shows them untracked) — check `git status` before assuming the fork is checked in.

**Docs are still the contract.** For framework mechanics: `docs/ARCHITECTURE.md`,
`docs/PRINCIPLES.md`, `docs/contracts/`. For **this bench specifically**:
[app/okaya_hvt/docs/INSTRUMENT_DRIVERS.md](app/okaya_hvt/docs/INSTRUMENT_DRIVERS.md) is
authoritative on instruments, wiring status, and known TODOs — read it before touching
instruments, the variable map, or step types here.

## This bench, specifically

- **Cloned from `okaya_transformer` (`TMF_Trx_Functional_Oakay`)** with the NI instrument and
  everything it alone backed — the motorised-Variac feedback/actuation subsystem, the
  `variac_regulate` step type, and the `okaya_maintenance` module — **excluded entirely**. This
  bench has no NI instance and no voltage-application mechanism defined yet; don't assume the
  Variac subsystem exists or reintroduce it without a deliberate design decision.
- **Controller**: Python controller (`app.json` `controller.kind: "python"`), config at
  [app/okaya_hvt/controller.json](app/okaya_hvt/controller.json), one station `st1`
  (`maps/st1.json`). Self-contained per `docs/TEMPLATE.md` §1.2: `library_paths` points at the
  fork root, not the central `Instrument_Library` — every driver this bench uses lives in this
  repo's own `instrument_libs/`.
- **Instruments** (Config → Instruments page, ids must match `maps/st1.json` `instance` names):
  - `relay1` — `waveshare_modbus_relay` (digital_output, **8ch, confirmed**). Authored in this
    fork; **real Modbus path verified live** (RTU-over-TCP, unit 1) against `192.168.10.16:4196`.
    Coil writes not yet exercised on hardware. Carries only the six `hipot_route_*` routes
    (Ch0-5; Ch6-7 unused) — the digital I/O (push buttons, safety curtain, emergency) and
    `dimmer_output`/`w1_meas`/`w2_meas`/`w3_meas` coil writes that used to share this card were
    removed 2026-09 (none were bound to any step type or recipe); re-add deliberately with
    confirmed real channel numbers if needed again.
  - `relay2` — same `waveshare_modbus_relay` driver, a **second, physically separate 8ch relay
    card** (2026-09, confirmed) dedicated to the tower-light stack: `tl_red` (Ch0), `tl_green`
    (Ch1), `buzzer` (Ch2) — only 3 of 8 channels used. **This bench has no Yellow tower
    light** (confirmed — no `tl_yellow` signal). Connection params (`host`/`port`/`unit_id`)
    are still **unconfirmed**.
  - `meco` — `meco_smp72` (analog_input). Sim-complete; **real register map still TODO**; not
    currently bound to any signal in `maps/st1.json` (orphaned, like `itech_it7300` below).
  - `itech_it7300` — power source driver, copied from the central library, **not wired to any
    instance on this bench** (orphaned carry-over). Starting point if a programmable AC/HV
    source is needed later; otherwise safe to delete.
  - `hipot` — `ut5320r` (UNI-T UT5320R+, `safety_tester` capability, non-scalar). Copied from the
    central library 2026-09; **real VISA/SCPI path confirmed live** (not the manual's Modbus
    path, which can't program a step's voltage/dwell). Reached only via the `hipot` action in
    `maps/st1.json`, never a scalar signal, driven by the `hipot_acw` step type (see below). Its
    `resource` connection string / target step number aren't pinned yet.
  - `selec_mfm384` (the AC meter that read input/winding voltage, current, and line frequency)
    **was removed 2026-09** along with the signals it fed (`input_voltage`, `no_load_current`,
    `winding_voltage1`, `winding_voltage2`, `line_frequency`) — this bench measures none of
    those today. Don't reintroduce it from git history; author a fresh driver against real
    hardware if a general AC meter is needed again.
- **Step types**: `app/okaya_hvt/okaya_hvt_steps/` — two:
  - `mux_measure` ([handler.py](app/okaya_hvt/okaya_hvt_steps/mux_measure/handler.py)):
    energizes a relay route, settles, reads one signal, judges it against `[min, max]`, and
    **always** opens the route in a `finally` (never leaves a tap energized on error/abort).
  - `hipot_acw` ([handler.py](app/okaya_hvt/okaya_hvt_steps/hipot_acw/handler.py)): same routing
    pattern, but invokes `measure_acw` on the `hipot` action instead of reading a scalar signal
    — leakage current (mA) + a `breakdown` flag, both judged, route always reopened. One shared
    step type across the bench's **six** test points (Primary/Secondary/Core/Feedback pairs, see
    `app/okaya_hvt/specs/hipot_acw.md`) — the six `hipot_route_*` relay channels (Ch0-Ch5, all on
    `relay1`) no longer collide with anything (the signals that used to share relay1 were
    removed 2026-09), but the channel numbers themselves are still unconfirmed against the real
    board; confirm before any live HV test. Real per-test-point voltage/dwell/current-limit
    numbers and the actual recipe are still to be authored. Starting/stopping the hipot test is
    **not** a variable-map signal — `measure_acw`
    issues SCPI `TEST` and polls to completion internally as one blocking call (checked against
    the real legacy control software's separate Start/Stop VIs; doesn't apply here — see
    `INSTRUMENT_DRIVERS.md`).
- **Frontend**: `frontend/src/app/overrides/recipe-editor.tsx` and `recipe-detail.tsx` are thin
  registry shims pointing at `okaya_hvt/HipotRecipeEditor.tsx` / `HipotRecipeDetail.tsx` /
  `HipotRecipeForm.tsx` (replaced the earlier Variac-based Transformer* form 2026-09, which
  built `variac_regulate` steps and read `selec_mfm384`-backed signals — neither exists on this
  bench). Six checkboxes (one per hipot test point), each revealing a panel with the three
  configurable params (ACW Voltage kV, Test Time sec, Max Current mA); `buildSteps`/`parseRecipe`
  map the form to/from one recipe `group` per selected test (id = the test key, e.g. `pri_sec`),
  each wrapping one `hipot_acw` step.
- **Bench tools**: `app/okaya_hvt/tools/` — `run_sim.py` (headless run with inline sim
  instances), `spec_lint.py`.
- **App config** (`backend/config/app.json`): branding "Okaya HVT Testbench"; modules enabled —
  `runs`, `auth` (local_db, roles `super_admin/admin/engineer/operator/maintenance`), `logs`,
  `recipe` (filesystem, step types from `okaya_hvt_steps`), `report` (sqlite + pass/fail folder
  sinks), `mes` (folder provider, gate/publish both disabled), `health`, `config`, `help`,
  `variables`. `updates.github_repo` is still the placeholder `<owner>/TMF_Trx_HVT_Okaya`.

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

# Standalone Python controller for this bench (normally backend auto-starts it)
cd controller
python -m pip install -e .
python -m controller ../app/okaya_hvt/controller.json
python -m pytest -q                      # live-broker tests skip if no broker on :1883

# Frontend
cd frontend
npm install
npm run dev                              # Vite :5173 (proxy → :8000)
npx vitest run                           # tests
npm run build                            # tsc + vite build (this is the type check)

# Bench-specific: headless in-process sim run against a recipe
python app/okaya_hvt/tools/run_sim.py <recipe.json>
```

Live config `backend/config/app.json` / `license.json` is gitignored — copy from the
`*.example.json` on first run. Dev login `admin` / `admin`. Mosquitto is expected at
`D:\tools\mosquitto\mosquitto.exe` (dev.ps1) or vendored under `deploy/vendor/mosquitto/`.

CI (`.github/workflows/ci.yml`, inherited from the framework, unmodified here): backend job on
`windows-latest` (`pip install -e ".[dev]"` → `pytest -q`); frontend job on `ubuntu-latest`
(`npm ci` → `npx tsc --noEmit` → `npx vitest run` → `npm run build`). Triggers on PRs and pushes
to `main` / `feat/**` / `release/**`.

## Architecture (inherited from the framework)

Three tiers, two seams:

```
Controller  ◄── MQTT only (tmf/{station}/…) ──►  Python backend  ◄── HTTP+WS ──►  React frontend
```

- **Controller** owns test execution: sequence, step timing, abort/timeout, safety, hardware. It
  is a **contract with two implementations** — the LabVIEW engine (`labview/`) or the standalone
  Python controller (`controller/`, imports nothing from `backend/`). This bench uses the Python
  controller (`app.json` `controller.kind: "python"`), which the backend supervises (start/stop
  with the app).
- **Python backend** (`backend/`) is the app platform and the **only web edge**. `core/` = module
  framework (registry, autodiscovery, manifests, activation gate) + services injected via
  CoreServices DI: `db` (SQLite, RAG envelope), `bridge` (MQTT client), `config` (JSON +
  JSONSchema), `diagnostics`, `auth` port, `web` (FastAPI, RFC-7807, `require_permission`),
  `streaming` (StreamHub). `run.py` boots uvicorn on a Windows **selector** event loop (aiomqtt
  requires it).
- **React frontend** (`frontend/`) talks only to Python (REST + WS), never to the broker. Vite +
  React + TS + MUI.

**MQTT grammar** (`docs/LABVIEW_BRIDGE.md`): `tmf/{station}/{class}/{name}` with classes
cmd/query/stream/value/event/diag/status; request/reply is MQTT-3.1.1-safe via payload
`reply_to` + `id`. Topics are rule-derived from this grammar, never stored per-variable.
Debugging starts with MQTT Explorer on `tmf/#`, not a stack trace.

**Modules** (`backend/modules/`): each has a `manifest.json`, the lifecycle construct → init →
start → stop → health, and is gated by config ∩ license at activation. Modules depend **only on
core, never on each other**, and consume **permissions (`DOMAIN.ACTION`), never roles**. This
bench has no app-specific `backend/modules/okaya_*` module (none created yet) — only stock
framework modules, per `app.json`'s module list above.

### Key cross-cutting facts

- **Instrument instances have one source**: the Config → Instruments page (v1.5.0). The
  variable engine and the supervised controller both consume its records; `controller.json`'s
  `instruments` list (this fork has none) is ignored under app supervision — instances live only
  in live config, not in git. Simulation is the per-instrument `simulated` toggle (v1.5.1) —
  there is no global sim mode under supervision.
- **Two instrument trees, don't confuse them**: `backend/instrumentlib/` is the framework
  capability **base/SDK** (`tmf-instrumentlib`, governed by `docs/INSTRUMENT_LIBRARY.md`);
  repo-root `instrument_libs/` (present in this fork) holds this bench's **own drivers** — see
  "This bench, specifically" above and `app/okaya_hvt/docs/INSTRUMENT_DRIVERS.md` for the full
  table, wiring status, and real-vs-sim verification notes.
- **Recipes are controller-native** (v1.3.0): steps are `{id, type, params}` against the
  controller's step-type catalog (8 core types + this app's `okaya_hvt_steps` package,
  currently just `mux_measure`).
- **Screen overrides** (`frontend/src/app/registry.ts`): this fork customizes the recipe editor
  and recipe detail screens via `frontend/src/app/overrides/{recipe-editor,recipe-detail}.tsx` —
  never by editing framework `screens/*`.
- **Data is JSON with JSON Schema** and a `schema_version` header; `*.example.json` ships, live
  file is gitignored. Persisted records carry the RAG envelope (id, type, ts, station,
  source_version, human-readable summary), append-only where possible.
- **Remote debugging** (`docs/REMOTE_DEBUG.md`): the Debug Server sidecar can record a bench to
  disk (rolling JSONL + 30 s failure snapshots) and be pulled to a laptop with the repo-root
  **`tmf-debug`** CLI (`tmf_debug/`). Captures + condensed `digest.json` land in **`.debug/`** at
  the repo root (gitignored): `tmf-debug why --host <bench> --last-run` writes both there, and
  `first_fault` in the digest is the highest-value field. On/off is Settings → Remote debugging
  (`app.json` `debug.enabled`), supervised by `station.py`.
- **Fork ownership boundary** (`docs/TEMPLATE.md` §1): app-owned paths in this repo are
  `app/okaya_hvt/` (step-type packages, variable map, recipes, `controller.json`),
  `instrument_libs/`, `frontend/src/app/overrides/`, and live config
  (`backend/config/*.json`). Everything else is framework code — a needed framework change goes
  upstream (`upstream` remote) and comes back via `git merge` on a release tag, never as a
  downstream patch (`docs/APP_REPO.md` "Upgrading to a newer framework").

### Skills

The framework's skills ship in `.claude/skills/` (inherited by this fork) and cover: forking a
new app from a bare framework tag (`new-test-app` — not needed here, already forked), forking a
new app FROM an existing similar forked app instead (`clone-test-app` — re-homes remotes to a
fresh framework tag, never the source app, then overlays + renames its app-owned payload; not
needed here either, but the one to reach for if a future sibling bench is close enough to this
one to start from it), generating a variable map from a System Blueprint spreadsheet
(`system-blueprint`), authoring controller step types (`test-step-authoring`), adding a test to
an existing app in dependency order (`add-bench-test` — driver → variable map → step type →
recipe → verify, the one most relevant to extending this bench), and authoring an instrument
driver (`create-instrument-library`, the one that produced this bench's
`waveshare_modbus_relay` / `meco_smp72` / `ut5320r`). Skills also live as a marketplace plugin
(`plugins/tmf-tools/`) for the terminal `claude` CLI — keep the two copies in sync when editing
one. See `docs/DEVELOPER_ONBOARDING.md`.

## Testing conventions

- Backend: pytest with `asyncio_mode = "auto"`; testpaths cover `tests/`, `modules/`,
  `debug_server/`, `instrumentlib/`. Integration tests that need a live broker skip cleanly when
  :1883 is down.
- Instrument drivers must pass the framework's conformance suite in **sim mode** before use
  (`create-instrument-library` skill); the two meter drivers here are sim-complete but their
  real register maps are still partially TODO (`meco_smp72`) — see
  `app/okaya_hvt/docs/INSTRUMENT_DRIVERS.md` for exactly what's verified live vs. assumed.
- The user verifies against real hardware / MQTT Explorer — do not write stub/placeholder
  implementations to fake a passing state.
- Failures must be loud and structured: typed diagnostic events + RFC-7807 bodies, never bare
  exceptions.

# ARCHITECTURE — current-state map

The bird's-eye view of what exists today and how the pieces fit. The authoritative
contracts are still [PRINCIPLES.md](PRINCIPLES.md), [CORE.md](CORE.md),
[LABVIEW_BRIDGE.md](LABVIEW_BRIDGE.md), and the per-module docs in
[contracts/](contracts/). This file is the index/overview that ties them together
and records the build status.

## The three tiers

```
┌────────────┐     MQTT only      ┌─────────────┐     HTTP + WS     ┌────────────┐
│  LabVIEW   │ ◄────────────────► │   Python    │ ◄───────────────► │   React    │
│ controller │  tmf/{station}/…   │ app platform│   127.0.0.1:8000  │  frontend  │
└────────────┘                    └─────────────┘                   └────────────┘
  test exec,                       modules, db,                       operator UI
  sequence, HAL,                   web edge, MQTT                     (sole edge =
  abort/safety                     bridge client                       Python)
```

- **Controller.** Owns test execution, sequencing, step timing, abort/timeout,
  safety, and hardware (HAL). Speaks MQTT only (3.1.1). It is a **contract with two
  implementations** — the LabVIEW engine, or the standalone Python controller in
  `controller/` ([PYTHON_CONTROLLER.md](PYTHON_CONTROLLER.md)); the app can't tell
  them apart. When Python is selected, the backend starts/stops it with the app.
- **Multi-station.** One PC runs N test sockets (`st1…stN`); one socket looks
  single-station. Controller selection, socket count, relaunch, and safe exit are
  in Settings → Station configuration ([MULTI_STATION.md](MULTI_STATION.md)).
- **Python = app platform + the only web edge.** Modules, SQLite, the web
  server, and the MQTT bridge client. Nothing else talks to the browser.
- **React = operator UI.** Talks only to Python (REST + WebSocket); never to the
  broker directly.

The MQTT seam grammar (`tmf/{station}/{class}/{name}`, classes cmd/query/stream/
value/event/diag/status) and the 3.1.1-safe request/reply (payload `reply_to`+`id`)
are defined in [LABVIEW_BRIDGE.md](LABVIEW_BRIDGE.md).

## Python platform (`backend/`)

`core/` — the platform: module framework (registry + autodiscovery, manifests,
activation gate with skip-and-continue), CoreServices DI, and the core services:

| Service | Role |
|---|---|
| `db` | SQLite Repository with the RAG envelope (id, type, ts, station, version, summary) |
| `bridge` | MQTT client — publish / request / serve / subscribe + latest-frame cache + link liveness from retained `status` |
| `config` | JSON + JSONSchema, example→live bootstrap, drift detection |
| `diagnostics` | structured diag bus |
| `auth` (port) | `TokenVerifier`; the Auth module fills it; fail-closed if no Auth |
| `web` | FastAPI install, RFC-7807 problems, request-id, CORS, `require_permission` |
| `streaming` | `StreamHub` fan-out for WS |

`run.py` boots uvicorn on a Windows **selector** event loop (aiomqtt needs it).
`/healthz` (alive), `/readyz` (core up + bridge link online), `/modules/status`.

## Modules (`backend/modules/`) — status

| Module | Entitlement | What it does | Status |
|---|---|---|---|
| `daq` | daq | AI/DI streaming + WS relays, station variables (read/write) | backend done; live needs real LabVIEW |
| `runs` | runs | run control proxy, run records, `/ws/station` + `/diagnostics/stream`, **barcode/recipe acquisition**, **test-result rows** | backend done |
| `auth` | auth | permission-first auth, sessions, full user management, **protected super_admin**, **temp-password creation** | backend done |
| `logs` | logs | error-log + action-log persistence, query/stats/retention | backend done |
| `recipe` | recipe | versioned recipes, **controller-native step-type catalog** (8 core + app step-type packages; the legacy 16-type path remains internally but is not surfaced), validation, `recipe.fetch` wire, export/import, diff | backend done; unified with the controller model (v1.3.0) |
| `report` | report | run reports + analytics (counts/yield/by-recipe), multi-sink (SQLite/folder, pass/fail), export | backend done |
| `mes` | mes | cross-station interlock (gate/publish), pluggable transport | backend done |
| `health` | health | check registry + sequencer, operator/technician/engineer UX, trends, scheduled runs, known-issues | backend done |
| `config` | config | station config centre (cascaded menu); **instruments** — the **single source of instrument instances** for the whole app (v1.5.0: variable engine + supervised controller consume its records; nothing reaches an instrument until configured here; simulation is the per-instrument `simulated` toggle, v1.5.1); transport-driven profiles + LabVIEW connection test (transport path hidden on python-controller apps); barcode/shift/MES sections follow | instruments done; live test needs real LabVIEW |
| `help` | help | in-app docs (user docs all-roles, developer docs super_admin) from the repo docs/ tree; context-aware **?** panel + `/help` page; future AI-chatbot corpus | done |
| `variables` | variables | variable engine (INSTRUMENT_LIBRARY §5.3): name → instrument scalar signal (scale/clamp); loads library packages + builds instances via `instrumentlib` registry — **auto-discovers the repo-root `instrument_libs/`** (a fork's copied drivers, v1.4.1) so no config wiring is needed; serves `variable.*` + `capability.request` over the bridge + REST `/variables` (+ `/libraries`, `/instances`) | IL2–IL4 done; central driver repo is `Instrument_Library`, forks carry copies |

Every module follows the same lifecycle (construct → init → start → stop →
health), declares a `manifest.json` (+ optional config schema), and is gated by
config ∩ license. Modules consume **permissions, never roles**.

## The MQTT command/event surface (Py ↔ LV)

- **Py → LV commands** (`cmd/{op}`, LabVIEW serves): `hello.echo`, `daq.*`,
  `variable.read/write`, `run.start`, `run.abort`.
- **LV → Py queries** (`query/{op}`, Python serves): `recipe.fetch` (LabVIEW
  pulls the substituted recipe JSON at run start).
- **LV → Py events** (`event/{kind}`): `run-started`, `test-result`,
  `run-finished` (PASS|FAIL|ABORTED), `run-aborted`, `step-*`, `safety-*`.
- **LV → Py streams/values**: `stream/ai|di` (latest-wins), `value/{name}`
  (retained).

Topics are **rule-derived** from the fixed grammar, not stored per-variable — see
[decisions/0001-no-topic-mapping-window.md](decisions/0001-no-topic-mapping-window.md).

## React frontend (`frontend/`)

Vite + React + TS + MUI. Talks only to Python. Full UI: shell + Login, Dashboard,
DAQ, Runs, Recipes (list/editor/view), Reports, Users — on a shared navy/green
"instrument console" theme with a light/dark toggle. See [FRONTEND.md](FRONTEND.md).

## Repo layout

```
backend/    Python — core/ platform + modules/ + tools/ + tests
  config/   app.example.json / license.example.json (live copies gitignored)
labview/    controller + DQMH Bridge module + variables.json (catalog, future)
frontend/   React app (src/: theme, components, screens, auth, hooks, api)
deploy/     mosquitto vendor + helper scripts
docs/       contracts (this folder) + acceptance walks + how-tos
dev.ps1     one-shot launcher: mosquitto + backend + frontend + browser
```

## Local dev

```pwsh
powershell -ExecutionPolicy Bypass -File .\dev.ps1   # broker + backend + frontend + login page
python station.py                                    # one-click: backend serves the built UI in a native window
```
Backend `:8000`, Vite `:5173`, Mosquitto `:1883`. Dev login `admin` / `admin`
(super_admin; a DEV credential — provision properly for production). In a shipped
station there is no Vite: the **Python edge also serves the built SPA** (single origin),
and `station.py` is the one-process launcher (broker + backend + desktop window, with a
graceful shutdown). See [RUNNING.md](RUNNING.md).

## Testing

- Backend: `cd backend; pytest -q` (190 passing). Per-module standalone testers
  under `modules/*/tester/` + integration under `tests/`.
- Frontend: `cd frontend; npx vitest run` (27 passing) + `npm run build` (tsc + bundle).

## Known desk work / deferred

- LabVIEW side: real DQMH Bridge (§12), DAQ/controller §5.1 command handlers,
  Test Sequencer `Execute` VIs, emitting `test-result`/`run-*` events with the
  Python-minted `run_id`.
- Licensing hardening (real signature verify); Variable Engine catalog
  (`labview/variables.json`); phase-2 scalable step-type sequence editor;
  PyInstaller frozen-sidecar packaging.

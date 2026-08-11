# Changelog

Framework releases. Semver (`docs/TEMPLATE.md` §versioning): **MAJOR** = a module
`contract_version` or locked-contract breaking change · **MINOR** = new modules /
features · **PATCH** = fixes. Every release is a git tag `v<version>`; the backend
stamps it into every record and diag event as `source_version`.

## v1.8.2 — 2026-08-11

Fix: Python controller test-result payload now matches the MQTT contract. PATCH.

- `controller.results.measurement_dict` emitted `value` + a step-id-prefixed `test_name` and no
  `measured`/`expected`, so the app UI + report (which read the documented `test_name`/`measured`/
  `expected` contract, MQTT_MESSAGES.md) showed **empty values everywhere** — dials, tables, and
  reports — even on a passing run. Now emits clean `test_name`, `measured`, `expected`, `result`
  (identical to the LabVIEW controller), keeping `qualified_name` (step_id.name) for report
  addressing and the raw `value`/`limits` for in-process consumers.

## v1.8.1 — 2026-08-11

spec-lint: uniform signal rule. PATCH.

- A test's Signals/actions are now checked the same way regardless of kind: every `set_output`
  and `measure_and_compare` signal the test's steps touch (reads must exist in the variable map),
  plus an authored step's `required_signals`/`required_actions` + its `action` param. Input-param
  ↔ schema stays authored-only (core steps use the fixed core schema).

## v1.8.0 — 2026-08-11

Literate test authoring — a spec `.md` per test + a drift gate (issue #5). MINOR.

- **`controller/controller/speclint.py`**: parses an authoritative per-test procedure spec
  (`app/<name>/specs/<test>.md` — front-matter + Input/Output/Signals tables) and checks it
  against the code that runs: input params ↔ the step type's `schema.json`, output measurements ↔
  what the step emits in a sim run, signals/actions ↔ `required_*`/the variable map. Reports
  drift (errors) so an edited `.md` can't silently diverge from the handler. The spec is the
  source of truth; the checker never rewrites either side.
- Spec template `docs/templates/test-spec.md`; `docs/TEST_SPECS.md` (format + round-trip loop);
  `specs/` added to the app-owned payload (TEMPLATE.md §1.1).
- The `test-step-authoring` / `add-bench-test` / `new-test-app` skills now emit and maintain
  these specs and run spec-lint as a gate.

## v1.7.0 — 2026-08-10

Serial-scan runs, branding logos, grouped nav (issue #6/#7 framework items). MINOR.

- **`fixed` barcode acquisition** (#6.2 follow-on / run-by-serial): a single-product bench
  scans a DUT **serial** — `runs.acquisition.barcode.strategy = "fixed"` + `recipe_id` always
  runs that recipe. Previously only `prefix` existed, so a scanned serial resolved to a bogus
  3-char recipe id and the run aborted at start.
- **Branding logos** (#7): `/branding` carries `logo_client` + `logo_exeliq` (data: URLs
  uploaded on Config → App identity, with preview). The header shows the **client logo
  top-left** and the **Exeliq logo top-right**.
- **Grouped navigation**: the drawer folds into Operations / Health / Config / Administration
  dropdowns (was a long flat list) to save space; Dashboard + Runs stay top-level.

## v1.6.0 — 2026-08-10

Operator-window hardening (issue #6, framework items). MINOR.

- **Maintenance mode works on a Python-controller app** (#6.2): the controller now serves
  `maintenance.enter`/`maintenance.exit` and publishes the retained `state/maintenance` the
  health module reads — previously only LabVIEW did, so entering maintenance timed out.
- **Full-screen toggle** in the AppBar (#6.4).
- **Navigation lock during a run** (#6.5): while a run is active the shell blocks the Back
  button + tab-close, the brand link goes inert, and every AppBar action but the test screen
  is hidden ("TEST IN PROGRESS") — only Abort is reachable. New `RunActivity` context.
- **Runs banner** (#6.6/#6.7): the Run ID is gone and an **Inspector** field shows the
  logged-in user.
- Exit backdrop resolves to "Station stopped — you can close this window" once the backend is
  really down, instead of an endless "shutting down…" spinner (#6.8).

## v1.5.1 — 2026-08-09

Simulation is per-instrument only. PATCH — fixes an Instruments-page `simulated: false`
being overridden by the app-level flag.

- The generated controller config always sets global `simulation: false`; each instrument
  runs simulated or real by its own Instruments-page **Simulated** toggle (the controller's
  force-all flag stays a standalone/dev knob for hand-written configs).
- `app.json` `controller.simulation` is **deprecated and ignored** (diag warning; dropped on
  the next Settings save). Settings → Station configuration loses its Mode select;
  `/system/station-config` no longer carries `simulation`.
- Docs: PYTHON_CONTROLLER.md, help `user/settings.md` + `user/instruments.md`, app schema.

## v1.5.0 — 2026-08-09

Instruments page = the single source of instrument instances. MINOR.

- The whole application — variable engine AND the supervised Python controller — now takes
  its instrument instances ONLY from Config → Instruments (`instrument` records, owner=python,
  enabled). An app with none configured starts the controller with **no instruments, even in
  simulation**.
- A `controller.json` `instruments` list is **ignored** under app supervision (diag warning
  with declared/configured counts). Standalone `python -m controller <cfg>` still honors it.
- Docs: PYTHON_CONTROLLER.md, TEMPLATE.md §1.1, help `user/instruments.md`.

## v1.4.1 — 2026-08-09

Fork instrument-library linkage. PATCH — restores the Instruments-config linkage in forks.

- The variables module **auto-discovers the repo-root `instrument_libs/`** (the drivers a fork
  copied from the central Instrument_Library, TEMPLATE.md §1.2) — no `app.json`
  `variables.library_paths` wiring needed. The Instruments page's Library dropdown now shows a
  fork's copied drivers automatically.
- `/branding` gains `controller` (kind). On a Python-controller app the Instruments page hides
  the LabVIEW-owned transport path and defaults new instruments to Python-owned.

## v1.4.0 — 2026-08-09

Per-app screen overrides. MINOR — additive; no contract breaks.

### Frontend screen-override registry
- New `frontend/src/app/overrides/` (app-owned) + `frontend/src/app/registry.ts`: a fork can
  replace the operator-facing screens — **Runs, Recipes, recipe editor/detail, Maintenance** —
  with app-specific React, **without editing framework `screens/*`**, so `git merge
  upstream/<version>` stays clean. An override file `default`-exports `{ key, component }`; an
  eager `import.meta.glob` registers it; `App.tsx` renders `APP_SCREENS[key] ?? <default>`.
- The framework ships `overrides/` empty → all screens use their defaults. Route permission
  wrappers (`RequirePermission`/`RequireRole`) stay in the framework — an override replaces only
  the inner screen. `tsconfig` now includes `vite/client` types (for `import.meta.glob`).
- Docs: `docs/TEMPLATE.md` §1.3 + `overrides/README.md`.

## v1.3.0 — 2026-08-09

Standalone Python controller, multi-station, station management, and the recipe/controller
step-type unification. MINOR — additive; no contract breaks. (Folds in the interim tags
v1.2.0 = station config + controller selection + safe exit + `safety_tester`; v1.2.1 =
`controller.config_file`.)

### Python controller (C7–C10)
- Standalone `controller/` — a peer implementation of the MQTT controller contract; the app
  can't tell it from LabVIEW. Safety (monitors-as-data, independent reflex loop,
  emergency_disable fan-out, teardown-skipped trip), simulation + `dry_run`, non-scalar
  actions (`ctx.invoke` + capability verify at load), app step-type packages + a CI gate.

### Multi-station & station management
- Settings → Station configuration: test-socket count (`st1..stN`, license-capped) +
  controller selection (`labview | python`); `/system/station-config`.
- The backend supervises the Python controller when `controller.kind = python`, using the
  app's `controller.config_file` (instruments / variable maps / step packages); graceful
  stop drives instruments to safe state. Safe **Exit** button (`/system/shutdown`) +
  `/system/relaunch`; `dev.ps1` runs under the launcher.
- `instrumentlib`: new `ISafetyTester` capability (hipot IR / AC-withstand).

### Recipe ↔ controller unification
- Canonical step-type catalog (`registry.catalog()`, JSON schemas for the 8 core types).
- Recipe module authors/validates/stores/lists/fetches **controller-native** recipes
  (`id`/`type`, nested groups) against the catalog (core + the app's `step_type_packages`);
  `/step-types` serves only that catalog (legacy 16-type authoring retired). Schema-driven
  recipe editor, same two-pane UI.
- Fixed a runs-module lost-update race (per-run lock) so every test-result persists.

### Framework template
- `TEMPLATE.md`: ratified the `app/<name>/` payload convention + self-contained driver copy
  (`instrument_libs/`). Global skills: `new-test-app` (fork the framework), `add-bench-test`
  (add a test in dependency order).

## v1.1.0 — 2026-07-14

Secure distribution + instrument features. MINOR — additive; no contract breaks.

### Secure distribution (Keystation)
- Licensing provider (`stub | keystation`) behind the existing License contract; the
  activation gate is unchanged. Fail-closed on missing SDK/DLL, unactivated, expired,
  tripwire. Three touch-points (startup, run-session, module gate).
- Activation surface: `/license/status|request|activate` + Settings → License
  (air-gapped `.ksreq → .kslease`). Product identity is config-driven
  (`licensing.product`) — framework vs per-customer app tier.
- Obfuscated release build (`build_release.py`, Nuitka) + `ci.yml` / `release.yml`.
- Signed code updates: ingest/resolve/apply `.ksupdate` (`/update/*`), **launcher**
  (`launcher.py`) that swaps the artifact on relaunch, "Relaunch to update" chip,
  GitHub-Release pull (`/update/check`). App-track signing (`tools/ks_release_signer`).
- Docs: `SECURE_DISTRIBUTION.md`, `RELEASE_HOWTO.md`.

### Instruments
- Instrument Test Bench — capability-driven manual control (super_admin), sourced
  from Config → Instruments; renders one group per capability.
- Composite multi-capability instruments (one library, several interface mix-ins,
  one connection); `resistance` + `frequency` capabilities; channel-arg variable
  binding. Libraries: Tenma 72-13360, Keithley DAQ6510 (both hardware-verified).

## v1.0.0 — 2026-07-04

First versioned release — the framework template baseline applications start from.

### Platform
- Core: module framework (register/variant, manifest, config schema), activation gate
  (config ∩ license, skip-and-continue), CoreServices DI + ports (auth, interlock),
  append-first Repository (RAG envelope, SQLite), diagnostics bus (+ MQTT mirror),
  MQTT bridge (request/reply, retained values, status + LWT), web shell
  (/healthz, /readyz), permissions (resolve-at-login, wildcard), config drift +
  config_doctor.
- Standard modules: daq, runs (test bench profile), auth (users/roles/sessions +
  editable permission matrix), logs, recipe (versioned authoring, zip bundles,
  step types), report (+ analytics), mes (interlock), health (operator-first checks,
  trends, schedules, known-issues), config (instruments/transports), variables
  (variable engine over instrumentlib), help (in-app user + dev docs).
- Frontend: React/TS/MUI instrument-console UI — test bench, recipes, reports,
  analytics, health/maintenance, config, users/permissions, settings, help.
- LabVIEW: MQTT Bridge + Sequence Engine sources; diag-emit VI library spec
  (LABVIEW_DIAG_EMIT.md).
- Sidecars & ecosystem: Debug Server (bus timeline, req/reply pairing, ring capture);
  `tmf-instrumentlib` 1.0.0 (instrument base + capability interfaces + conformance
  suite) consumed by the external Instrument_Library repo.

### Contracts
PRINCIPLES, CORE, LABVIEW_BRIDGE, LOGGING/diag-emit, DATA_TRANSFER (via bridge),
STEP_TYPES, RECIPE, HEALTH_CHECK, MES, CONFIG, INSTRUMENT_LIBRARY, DEBUG_SERVER.

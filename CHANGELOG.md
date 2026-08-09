# Changelog

Framework releases. Semver (`docs/TEMPLATE.md` §versioning): **MAJOR** = a module
`contract_version` or locked-contract breaking change · **MINOR** = new modules /
features · **PATCH** = fixes. Every release is a git tag `v<version>`; the backend
stamps it into every record and diag event as `source_version`.

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

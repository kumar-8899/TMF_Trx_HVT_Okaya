# Changelog

Framework releases. Semver (`docs/TEMPLATE.md` §versioning): **MAJOR** = a module
`contract_version` or locked-contract breaking change · **MINOR** = new modules /
features · **PATCH** = fixes. Every release is a git tag `v<version>`; the backend
stamps it into every record and diag event as `source_version`.

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

# TEMPLATE.md — Using the framework as a versioned starting point

Super_Test_App is the **framework repo**. Applications do not develop in it — they
start from a **released tag** and stay downstream. This doc is the contract for that
relationship: what an application may touch, how it upgrades, how releases version.

Model today: **template fork** (Model A). The framework is merged in by git; the rule
that makes merges clean is the ownership boundary below. Long-term (Model B) pieces
graduate to pinned packages the way `tmf-instrumentlib` already did.

---

## 1. Ownership boundary — the one rule that prevents drift

**An application only creates/edits app-owned paths. Framework-owned files are
read-only downstream.** If an app needs a framework change, change it in the
framework repo and release — never patch it in the app fork.

### App-owned (yours, never touched by upstream merges)
| Path | What |
|---|---|
| `backend/config/app.json`, `license.json` | live station config + license (framework ships only `*.example.json`) |
| `backend/config/known_issues/`, station data dirs | site data |
| `backend/data/` | runtime DB, recipes, reports (gitignored) |
| `backend/modules/<app>_*/` | application-specific **backend** modules — **prefix with the app name** (e.g. `acme_eol/`) so upstream module additions can never collide |
| `app/<name>/` | the **app payload** — controller step-type packages, variable maps, recipes, the app's controller config, app tools/tests/docs. See §1.1. |
| `instrument_libs/` (repo root) | instrument **drivers this app uses**, COPIED from the central `Instrument_Library` repo — the app is self-contained, it does not reference the central repo at runtime. See §1.2. |
| `labview/App/` | application LabVIEW: test-case VIs, HAL, station wiring (see §4) |
| `frontend/src/app/overrides/` | app **screen overrides** — per-app Runs/Recipe/Maintenance UI. The framework ships this dir empty; a fork drops `*.tsx` files here to replace a screen without editing framework `screens/*`. See §1.3. |
| branding block + `controller` block in `app.json` | name/product shown in the UI; controller selection (labview\|python) + `config_file` (no source edits) |

### Framework-owned (read-only in an application)
`backend/core/`, `backend/instrumentlib/` (the capability **base/SDK** — not drivers),
the standard `backend/modules/*` (daq, runs, auth, logs, recipe, report, mes, health,
config, variables, help), `backend/debug_server/`, `controller/` (the Python controller
engine — app step types are added under `app/<name>/`, never by editing `controller/`),
`frontend/` (**except** `frontend/src/app/overrides/` — see §1.3), `docs/`,
`labview/Source/` framework modules (MQTT Bridge, Sequence Engine),
`dev.ps1`, `debug.ps1`.

Custom recipes, users, instruments, variable maps, health suites, MES settings,
permissions — **all data/config**, not code. That is the point of the design
(PRINCIPLES §1): most "application development" happens in app.json + the UI.

---

## 1.1 The app payload — `app/<name>/`

Controller-side app content has no home under the backend/LabVIEW slots above, so it
lives in one app-owned tree, `app/<name>/`, kept apart from framework files:

| Path | What |
|---|---|
| `<name>_steps/` | **controller step-type package** — product-specific step types (e.g. `hipot_ir`), loaded via `step_type_packages`. Only what the core 8 types can't express; author with the `test-step-authoring` skill. |
| `maps/<station>.json` | **variable map** — named signals (read/write + scale) and actions bound to instrument capabilities. |
| `recipes/*.json` | **recipes** — the test sequences + limits, as data. |
| `controller.json` | the app's **controller config** — instruments, `library_paths` (→ the fork's own `instrument_libs/`), station→map, `step_type_packages`. Referenced by `app.json` → `controller.config_file`. |
| `tools/`, `tests/`, `docs/` | app runner (e.g. `run_sim.py`), sequence tests, app docs. |

Wire it in `app.json`: `"controller": { "kind": "python", "config_file": "app/<name>/controller.json" }`.
The backend then auto-starts the Python controller with this config (`controller.config_file`,
v1.2.1+).

## 1.2 Instrument drivers — copy from central, self-contained

Drivers live in the central `Instrument_Library` repo. A fork **copies in only the
drivers it uses**, into the fork's own `instrument_libs/` (repo root) — it never
references the central repo at runtime. `controller.json` `library_paths` points at the
**fork**, not central. Do not confuse `instrument_libs/` (drivers) with
`backend/instrumentlib/` (the capability base/SDK the drivers are written against).
The `new-test-app` skill automates the copy; the manual procedure is the per-app
`app/<name>/docs/INSTRUMENT_DRIVERS.md`.

## 1.3 Screen overrides — per-app Runs/Recipe/Maintenance UI

The operator-facing screens (Runs, Recipes, the recipe editor/detail, Maintenance) are not
one-size-fits-all — a wire-feeder bench wants a gauge dashboard, another app wants a checklist.
The framework exposes a **screen-override registry** so a fork changes these screens **without
editing framework `screens/*`** (which would conflict on every `git merge upstream/<version>`).

How it works (`frontend/src/app/registry.ts`):
- The framework ships `frontend/src/app/overrides/` **empty** → all screens use their defaults.
- A fork drops `overrides/<something>.tsx` that `default`-exports `{ key, component }`.
- An eager `import.meta.glob` registers it; `App.tsx` renders `APP_SCREENS[key] ?? <default>`.

| key | default | route(s) |
|---|---|---|
| `runs` | `screens/Runs` | `/runs` |
| `recipes` | `screens/Recipes` | `/recipes` |
| `recipe-editor` | `screens/RecipeEditor` | `/recipes/new`, `/recipes/:id/edit` |
| `recipe-detail` | `screens/RecipeDetail` | `/recipes/:id` |
| `maintenance` | `screens/Maintenance` | `/maintenance` |

The permission wrappers (`RequirePermission`/`RequireRole`) stay in the framework `App.tsx` —
an override replaces only the inner screen, never the gate. Overrides reuse the framework API
client and run-stream hooks. See `frontend/src/app/overrides/README.md`.

---

## 2. Starting an application

```pwsh
git clone <framework-remote> App_<Customer>
cd App_<Customer>
git checkout v1.0.0                      # a RELEASE TAG, never main
git remote rename origin upstream        # framework stays as 'upstream'
git remote add origin <app-remote>       # the application's own repo
git switch -c main && git push -u origin main

cd backend
copy config\app.example.json config\app.json
copy config\license.example.json config\license.json
pip install -e instrumentlib ; pip install -e .[dev]
cd ..\frontend ; npm install
.\dev.ps1                                # broker + backend + frontend
# login admin/admin (DEV credential) -> change it; set branding in app.json
```

Then per application: set `station` + `branding` + the `controller` block, enable/disable
modules + license, define roles/permissions, and build the LabVIEW app layer (if any)
against `LABVIEW_BRIDGE.md`. For a **Python-controller** app also:

- **Copy the drivers** it uses from central `Instrument_Library` into `instrument_libs/`
  (see §1.2 / `app/<name>/docs/INSTRUMENT_DRIVERS.md`).
- **Create the app payload** under `app/<name>/` (§1.1): step-type package, variable map,
  recipe(s), `controller.json`.
- **Wire** `app.json` → `"controller": { "kind": "python", "config_file": "app/<name>/controller.json" }`.

Prefer the **`new-test-app` skill** (global Claude Code skill) — it does the clone, remotes,
driver copy, app payload scaffold, config wiring, install, and a sim verification, gathering
the bench details conversationally. `tools/new_app.ps1` is the older mechanical scaffolder.

---

## 3. Upgrading an application to a new framework release

```pwsh
git fetch upstream --tags
git merge v1.1.0                         # clean IF §1 was respected
cd backend
pip install -e instrumentlib ; pip install -e .[dev]
python tools\config_doctor.py           # dry-run: new modules/roles/permissions
python tools\config_doctor.py --apply   # additive reconcile of live config
python -m pytest -q
cd ..\frontend ; npm install ; npx vitest run ; npm run build
# restart backend + re-login (permissions/modules resolve at login/boot)
```

Read `CHANGELOG.md` first: **MAJOR** releases may change module contracts — check
your `<app>_*` modules against the new `contract_version` before merging.

---

## 4. Versioning policy (semver)

- Version lives in `backend/core/__init__.py` (`__version__`) + `backend/pyproject.toml`;
  every record/diag event carries it as `source_version`.
- **MAJOR** — any module `contract_version` bump or a locked-contract
  (PRINCIPLES/CORE/BRIDGE/…) breaking change.
- **MINOR** — new modules, new features, additive contract growth.
- **PATCH** — fixes.
- Release = update version + `CHANGELOG.md`, tag `v<version>`, push tag.
  Sub-distributions version independently: `tmf-instrumentlib` (= `base_version`,
  INSTRUMENT_LIBRARY §9).

## 5. LabVIEW split (planned boundary)

Target: `labview/Source/` = framework only (MQTT Bridge, Sequence Engine, diag-emit
lib); `labview/App/` = per-application VIs (test cases, HAL). `.vi` files are binary —
git cannot merge them, so the framework/app boundary MUST be directory-level. The move
must be done **inside the LabVIEW IDE** (the `.lvproj` tracks paths); do not move
`.vi` files with the file system.

## 6. Graduation path (Model B, later)

When an extension point stabilizes, extract it as a pinned package instead of merged
source — done: `tmf-instrumentlib`. Candidates next: backend platform (`tmf-backend`
wheel + entry-point module discovery), frontend as a built bundle with config-driven
branding/nav. Each graduation shrinks the merge surface until an application repo is
config + custom modules + LabVIEW only.

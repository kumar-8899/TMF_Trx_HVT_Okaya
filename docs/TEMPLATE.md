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
| `backend/modules/<app>_*/` | application-specific modules — **prefix with the app name** (e.g. `acme_eol/`) so upstream module additions can never collide |
| `labview/App/` | application LabVIEW: test-case VIs, HAL, station wiring (see §4) |
| branding block in `app.json` | name/product shown in the UI (no source edits) |

### Framework-owned (read-only in an application)
`backend/core/`, `backend/instrumentlib/`, the standard `backend/modules/*`
(daq, runs, auth, logs, recipe, report, mes, health, config, variables, help),
`backend/debug_server/`, `frontend/`, `docs/`, `labview/Source/` framework modules
(MQTT Bridge, Sequence Engine), `dev.ps1`, `debug.ps1`.

Custom recipes, users, instruments, variable maps, health suites, MES settings,
permissions — **all data/config**, not code. That is the point of the design
(PRINCIPLES §1): most "application development" happens in app.json + the UI.

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

Then per application: set `station` + `branding`, enable/disable modules + license,
add instruments (Config → Instruments), author recipes, define roles/permissions,
wire the Instrument_Library (`variables.library_paths` or pip pin), and build the
LabVIEW app layer against `LABVIEW_BRIDGE.md`.

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

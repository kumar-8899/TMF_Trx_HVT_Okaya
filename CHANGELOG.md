# Changelog

Framework releases. Semver (`docs/TEMPLATE.md` §versioning): **MAJOR** = a module
`contract_version` or locked-contract breaking change · **MINOR** = new modules /
features · **PATCH** = fixes. Every release is a git tag `v<version>`; the backend
stamps it into every record and diag event as `source_version`.

## v1.26.0 — 2026-09-29

**Narrow the Nuitka compile surface + app-payload-only patch updates (MINOR).**

App-track builds took the full analysis+codegen hit on every build (only the C-compiler step was
cached), and the update pipeline could only ever swap the entire `run.dist` tree — so a one-line
bugfix in a customer's step type cost the same build time and swap risk as a framework upgrade.
Neither was actually protecting framework IP: per `CLAUDE.md`'s fork-ownership boundary,
`app/<name>/` is app-owned code, not Super_Test_App's. See ADR
[0002](docs/decisions/0002-nuitka-compile-scope.md).

- `--track app` builds no longer force-compile the app's `step_type_packages` /
  `library_packages` / `instrument_libs` by default — they ship as plain `.py` under
  `run.dist/app/<product>/` + `run.dist/instrument_libs/` instead, loaded at runtime via the
  controller's existing `step_type_paths`/`library_paths` mechanism
  (`controller_supervisor.py` now auto-appends the right directories). `core`/`modules`/
  `controller` — the actual framework IP — are unaffected. `--compile-app-payload` opts back
  into the old fully-compiled behavior for a fork that wants its own step types/drivers
  protected too.
- New `package_app_payload_artifact()` produces a supplementary `<slug>-<version>-app-payload.zip`
  release asset. `core/services/updates.py` and `launcher.py` gained scope-aware staging: a
  release can sign either the full artifact or `package_app_payload_artifact`'s smaller one
  (`tools/ks_release_signer/sign_update.py`'s `KS_ARTIFACT_SCOPE`); the station **detects** which
  kind it received from the hash-verified content itself (never a signed manifest field — that
  would have been an unsigned, spoofable side-channel, see ADR 0002) and swaps only
  `run.dist/app` + `run.dist/instrument_libs` for an app-payload artifact, leaving `run.exe`
  untouched. See `docs/UPDATES.md` §3.2/§4.1a.
- New `deploy/build-update-package.ps1` + `update-package.iss.template` (`cut-release.ps1
  -BuildUpdatePackage`): an Inno-built `<AppShort>-Update-<ver>.exe` that drops an already-signed
  update (full and/or app-payload scope) into an existing install's fixed incoming-update slots —
  for an air-gapped fleet, no more hunting for where two files go or typing paths. New
  `UpdateService.scan_incoming` / `POST /update/scan-incoming` / the Updates page's **"Scan for
  updates on this PC"** button stage whatever the tool dropped, through the identical
  verify/hash/stage pipeline as every other update path. Rollback (to a local backup) is
  unaffected either way — it never needed file delivery. See `docs/DEPLOY_STATION.md`'s
  air-gapped section and `docs/UPDATES.md` §3.3.

## v1.25.0 — 2026-09-28

**Barcode Start dialog: scan-to-submit is now opt-in, not the unconditional default (MINOR).**

Found on a real downstream fork (`framework-fix-prompt-2.md` Issue 1) while building a bench-specific
two-hand hardware-button start feature: the Start dialog's serial-number field started the run on
Enter unconditionally, and every barcode scanner ships configured to send Enter after each scan —
so "scan the unit" and "start the test, energizing hardware" were the same physical action, with no
beat for an operator to review the resolved recipe first.

- Enter in the Start dialog's serial-number field now only populates the field by default; starting
  the run requires the explicit **Start** button click.
- Added a per-fork opt-in: barcode config (`GET`/`PUT /config/barcode`) gains `submit_on_enter`
  (bool, default `false`), with a matching toggle on **Config → Barcode**
  (`frontend/src/screens/config/Barcode.tsx`) — a bench where nothing is gained by that review beat
  can switch scan-to-submit back on.

## v1.24.2 — 2026-09-28

**Downstream fork fixes: a bad instrument no longer kills the whole controller, cycle time reaches
reports, and results tables render human-readable (PATCH).**

Three issues found on a real downstream hardware fork (`framework-fix-prompt.md` Issues 6–8),
all in framework-owned code.

- **Controller — one misconfigured instrument no longer takes the whole bench offline.**
  `InstrumentRegistry.build()` (`controller/controller/instruments/registry.py`) now catches a
  driver's `__init__` raising (a real-hardware guard, a missing param, an unreachable resource)
  the same way it already handled an unknown library: the instance is skipped and recorded with a
  reason, every other instrument still constructs and connects, and the controller process itself
  keeps running. Surfaced via the existing `status()`/`instrument.status` `state: "skipped"` shape,
  so the Instruments page shows *which* instrument is the problem instead of every instrument
  going dark.
- **Controller — `cycle_time_ms` now reaches every report row.** `Sequencer._attempt`'s correctly
  computed `elapsed_ms` never reached the per-measurement `test-result` event
  (`measurement_dict()` had no timing field); every report (CSV/JSON/DB) had a blank
  `cycle_time_ms` column, always. The report pipeline (`backend/modules/report/assembly.py`, its
  schema) was already wired for this field — only the value was missing.
- **Frontend — results tables render rounded, human-readable values.** `ResultsTable.tsx` (used by
  both the live Runs screen and the historical Reports view — the one shared framework component a
  fork cannot override) now rounds numeric `measured`/`expected` values to 2 decimal places and
  Title-Cases a `snake_case` `test_name` (e.g. the framework's own `set_output` step type, which
  always names its measurement after the raw signal id) — a no-op on a name a recipe author
  already wrote as human-readable text, and on a pre-formatted range string like `"229.0–231.0"`.

## v1.24.1 — 2026-09-27

**Station launcher: maximized by default (not kiosk), and a clean shutdown from the title-bar close button (PATCH).**

- `station.py`/`run_station.exe` now open **maximized** by default (title bar, resizable, taskbar
  visible) instead of a fixed 1440×900 window. `--fullscreen` still gives the old kiosk-style window
  (no title bar) for benches that want it.
- The OS **title-bar close (X) button** is now bound explicitly (`window.events.closing`) to the
  same graceful teardown as the in-app **Exit station** button — CTRL_BREAK to the backend, modules
  stop, the controller drives every instrument to a safe state, then the broker stops. Previously
  this depended on `webview.start()` merely returning; it's now deterministic.
- The installer's Desktop/Start-Menu/post-install shortcuts (`deploy/installer.iss.template`) dropped
  `--fullscreen`, so newly built client installers open maximized too. Existing installs keep
  whatever shortcut they already have; re-run the installer (or edit the shortcut) to pick this up.

## v1.24.0 — 2026-09-21

**User Portal: a built-in replacement for the printed software manual, with a searchable PDF library (MINOR).**

R-B of the Developer Hub / User Portal plan. New framework module **`portal`** (`docs/contracts/PORTAL.md`);
it never touches MQTT — it works over stored data, so it also runs on air-gapped stations.

- **Portal screen** (`/portal`, side-menu **Portal**, needs `PORTAL.VIEW`): a **Manual** tab (the help viewer,
  user audience only, links stay in the portal) and a **Library** tab.
- **Library — hardware manuals and drawings as PDFs.** Upload (`PORTAL.UPLOAD`), edit title/tags, delete
  (`PORTAL.MANAGE`), open in a full-screen viewer, **Save a copy** to the PC's Downloads folder. The viewer is
  the browser/WebView2's native PDF viewer (page navigation, zoom, search, print) — verified in a real
  pywebview window, so no `pdf.js` dependency. Uploads are a raw `application/pdf` body (no multipart
  dependency), size-limited from `Content-Length` before reading (default 50 MB), PDF-header checked and
  de-duplicated by SHA-256. Files live under the state root, so an in-app update never loses them.
- **Search inside the PDFs.** `pypdf` extracts text; an in-memory SQLite **FTS5** index (bm25 + snippets)
  is rebuilt from the durable records — no extra tables in the station database. Scanned PDFs are stored and
  viewable and flagged *not searchable*; hostile query text is sanitised; without FTS5 it falls back to a
  substring scan.
- **The manual can now be the app's own.** Help discovers `app/<name>/portal/*.md` (front matter `title,
  section, order, route`; default section **This app**) plus images (`![alt](asset:app/<file>)`) and bundled
  read-only PDFs (`app/<name>/portal/library/`), all **app-owned** (TEMPLATE.md §1) and shipped in a built
  station (`build_release.copy_app_payload` now includes `portal/`).
- **The user manual has screenshots.** 17 user pages embed the shared image library (added in v1.23.0);
  two portal screens were captured for the manual; the capture pipeline can now run on another port.
- New permissions `PORTAL.VIEW` (every role), `PORTAL.UPLOAD` (admin, engineer), `PORTAL.MANAGE` (admin),
  `PORTAL.*` (super_admin). **Existing stations: run `python -m tools.config_doctor --apply` and log in again**
  to pick up the module, its entitlement and the role grants.
- Core: `core.services.docs_paths` (docs root + app portal folders, shared by help and portal) and
  `core.services.downloads.save_to_downloads`. New dependency: `pypdf>=4` (pure Python; included in the frozen
  build).
- Tests: portal module tester (upload/limits/dedupe/search/permissions/persistence/bundled seeds/Downloads),
  help app-page + app-asset tests, build test for the app payload, and frontend tests for the Library, PDF
  viewer and Portal (permission gating, upload, errors, viewer lifecycle). The assistant / troubleshooting
  center follows in v1.25.0.

## v1.23.0 — 2026-09-21

**Developer Hub: an interactive, self-updating developer guide in Help — and developer docs never ship to a client station (MINOR).**

Handover tooling for developers building apps on the framework, plus the shared foundation the upcoming
User portal reuses. Design: `docs/DEVELOPER_HUB.md`.

- **New: Help → Developer → Developer Hub** — start page, a guided 30-minute first-app checklist, mental
  model + architecture diagram, principles ("what they mean for you"), an **ownership-boundary explorer**
  (type a path → framework- or app-owned?), building-blocks chain, a **skill picker**, generated
  facts & figures, a release feed with upgrade recipe, a contracts map, a developer glossary and a
  Gotchas & FAQ seeded from real incidents. The Developer section is regrouped (Start here / Concepts /
  How-to / Reference / Contracts / Bus & LabVIEW / Stay current).
- **Facts can't go stale.** `tools/gen_devguide.py` generates `docs/generated/facts.{json,md}` from the
  code (version, CHANGELOG feed, module manifests, permission catalog + default roles, step-type catalog,
  capability interfaces, controller MQTT ops, route decorators, frontend routes, skills). A drift test and a
  CI step fail when they are out of date; the facts embed the version so a release can't skip regenerating.
- **Help platform upgrades** (framework-wide, also used by the user manual): shared **image library**
  (`docs/assets/manifest.json` + authenticated `/help/asset/<id>`, "captured at vX" badge and a warning when a
  screen changed since capture), live **widgets** via ```` ```tmf:<name> ```` blocks (unknown → visible error),
  in-app `help:` links, heading anchors, code-block copy buttons, **deep links** (`/help?page=<id>#anchor`),
  catalog integrity gates (no duplicate ids — one existed —, every `docs/help/**.md` registered, every
  `help:`/`asset:`/`tmf:` reference resolves), and the first frontend tests for Help.
- **Screenshot pipeline** (dev-only, `tools/screenshots`): Playwright drives the installed Edge against a
  seeded simulated station and writes `docs/assets/screens/*.png` + manifest entries stamped with the
  framework version and a hash of each screen's source file.
- **Developer docs are no longer shipped.** `build_release.copy_user_docs` replaces "copy all of `docs/`"
  (which put PRINCIPLES/ARCHITECTURE/contracts/`help/dev` on every client station) with an **allowlist**
  (`docs/help/user/**` + the images the user-audience manifest references), and the help catalog hides every
  developer page, asset and `/help/facts` in a frozen build (defence in depth, both tested).
- Fixes: `HelpContract` protocol matched to the implementation; developer pages that were orphaned
  (onboarding, deploy, test specs) are now reachable.
- **Fix (found while capturing screenshots): a browser could show `Unexpected token '<' … is not valid JSON`
  on pages whose URL is also an API path** (`/recipes` and similar — e.g. after F5). The SPA shell response
  for a navigation carries `ETag`/`Last-Modified` but no cache headers, so the browser could answer the
  page's own `fetch('/recipes')` from the cached HTML. Shell responses now send `Cache-Control: no-cache`
  and `Vary: Accept` (regression test in `tests/test_spa.py`).

## v1.22.1 — 2026-09-16

**Fix: `run_station.exe` could compile but never open a window (PATCH).**

Reproduced for real on a live app fork (`TMF_Trx_HVT_Okaya`): v1.20.0's adaptive-retry compile
(Issue 4) resolves Nuitka's `FATAL: Conflict between user and plugin decision for module
'webview.platforms.win32'` by agreeing to exclude `win32` from the build — the compile then
succeeds, but `webview/platforms/winforms.py` (the only Windows GUI backend pywebview has)
imports `win32` as a required helper, not an optional platform variant, so it throws
`ImportError` the instant it tries to open a window. The backend still boots fine, so this only
surfaces as "no window ever appears" — caught by v1.20.0's own windowed-verification gate
(working as designed), but not actually fixed by the retry.

- **Fix:** `build_run_station_exe` now passes `--disable-plugin=pywebview` to Nuitka, removing
  its (wrong) opinion about `webview.platforms.*` entirely, and excludes only a **fixed** set of
  genuinely Windows-irrelevant platforms (`android, cocoa, gtk, qt, mshtml, edgehtml, cef`) —
  `win32` is deliberately left out, so Nuitka's ordinary static import-following includes it on
  its own (since `winforms.py` imports it), with nothing left to veto it. No adaptive retry
  needed: unlike the plugin's own allow-list, `winforms.py`'s import graph doesn't vary by
  Nuitka/pywebview version. Verified live on this fix: a real `run_station.exe` compiled and
  opened an actual window.
- The adaptive-retry machinery (`_WEBVIEW_NOFOLLOW_ALWAYS`, `_nuitka_webview_conflict`) is
  removed along with its now-obsolete tests; `backend/tests/test_build_release.py` gained
  coverage locking in the fixed exclude list and that a compile failure no longer retries.

## v1.22.0 — 2026-09-15

**Frontend: forks can add a brand-new page, not just replace one of the 5 fixed screens (MINOR).**

Found on a downstream bench (framework Issue 3): the screen-override registry
(`frontend/src/app/overrides/`) only let a fork *replace* Runs/Recipes/recipe-editor/
recipe-detail/Maintenance — there was no way to *add* a new top-level page without editing
framework-owned `App.tsx` (routes) and `Layout.tsx` (nav), which breaks the clean-merge
boundary `docs/TEMPLATE.md` §1 exists to protect.

- **New:** any file in `overrides/` can export a named `pages: AppPage[]`
  (`{ path, navLabel, navIcon?, permission?, component }`) alongside or instead of its
  `default` screen override. Each entry becomes a route — permission-gated via
  `RequirePermission` the same way a built-in route is — and a nav-drawer item,
  automatically; `App.tsx`/`Layout.tsx` render `APP_PAGES` without knowing what a fork put
  in it.
- `path` **must start with `"/app/"`** — reserved for app-contributed pages so they can never
  collide with a framework route added in a later release. An entry that doesn't (or is
  missing `navLabel`/`component`) is skipped with a console warning, not a crash.
- Registry logic (`frontend/src/app/registry.ts`) is now a pure, unit-tested `buildRegistry()`
  the Vite `import.meta.glob` result feeds — new coverage in `registry.test.ts`. Docs:
  `docs/TEMPLATE.md` §1.3, `frontend/src/app/overrides/README.md`.

## v1.21.0 — 2026-09-15

**Python controller: hardware ops no longer block command dispatch (MINOR).**

Found on a real Okaya bench running the supervised Python controller (framework Issue 2).
paho dispatches every MQTT message on **one network thread**; the controller's hardware
handlers (`variable.read/write/read_many`, `instrument.test`, `instrument.call`) blocked
that thread for the full device round-trip via `loop.run(inst.invoke(...), timeout=...)`.
A slow or hung instrument therefore froze **all** command handling — every other
instrument's reads, `hello.echo`, `instrument.status`, keepalive — and could make shutdown
miss its grace window.

- **`StationClient.serve(op, handler, blocking=True)`** now routes an op to a small daemon
  dispatch pool (`controller/controller/bridge/client.py::_DispatchPool`, 8 workers) instead
  of running it inline on the network thread; `_on_message` hands off and returns at once.
  Hardware ops are served `blocking=True`; fast, non-hardware ops (`hello.echo`,
  `instrument.status`, run/safety/maintenance) stay inline for minimum latency.
- Per-instrument serialization is unchanged — `InstrumentBase`'s per-instance `asyncio.Lock`
  still means same-instrument calls serialize while distinct instruments run concurrently.
  The pool's workers are daemon threads, so a hung device call can never block
  `StationClient.stop()` or process exit.
- New live-broker acceptance (`controller/tester/test_integration_c2_dispatch.py`): a slow
  `instrument.call` in flight no longer delays a concurrent `hello.echo`, `instrument.status`,
  or a different instrument's call; same-instrument calls still serialize; `stop()` returns
  promptly with a hung call in flight.

## v1.20.0 — 2026-09-15

**One run entrypoint + one build/release entrypoint, and two clean-PC first-install fixes (MINOR).**

Consolidation — fewer files to run and to release:
- **`station.py` is now the single run entrypoint** for every layout (source dev/prod + frozen).
  It always supervises the backend via `launcher.Supervisor` in-process (the proven model), adds
  Vite/HMR + frontend build only in a source checkout, and detects the frozen `run.dist` layout
  automatically. The duplicate **`run_station.py` is removed** — `run_station.exe` is now
  `station.py` Nuitka-compiled (same exe name, so installers/shortcuts are unchanged).
  **`dev.ps1` is now a one-line shim** for `python station.py --dev`.
- **`deploy/cut-release.ps1` is now the single build/release entrypoint** — a plain file every fork
  inherits (no more `.template` render; it auto-detects the app under `app/`, or takes `-Slug`). It
  invokes `fetch-mosquitto.ps1`, `build_release.py`, the signer and `build-installer.ps1` internally;
  a new **`-BuildOnly`** mode builds the artifacts without committing/tagging/publishing. Framework
  releases stay the git-tag flow (RELEASE_HOWTO.md — the framework builds no binary).
- `launcher.Supervisor` gained a `show_backend_console` flag so a source/dev run shows the backend's
  logs while the frozen windowed launcher keeps suppressing a console window.

Fixes (first-install blockers on a genuinely clean client PC):
- **Issue 4 — the frozen windowed launcher is now verified to actually open a window.** The build's
  runtime smoke test used to launch `run_station.exe --no-window` and only check `/healthz`, so an
  exe that booted the backend but could never open a pywebview window (a Nuitka/pywebview plugin
  interaction) shipped "verified." It now launches the exe **windowed** and confirms a real window
  appears (matched by the owning process's image name, since Nuitka onefile spawns a child), failing
  soft — removing the exe with an unlink backoff — if none does. The adaptive-retry compile is
  unchanged; windowed verification catches a bad exe regardless of how it was compiled.
- **Issue 5 — the vendored Mosquitto broker now ships the MSVC runtime it needs.** `mosquitto.exe`
  hard-imports `VCRUNTIME140.dll` (+`140_1` for `mosquittopp.dll`); a clean PC without the VC++
  redistributable couldn't start it, so the broker never bound `:1883` and it surfaced as a bare
  connection-refused. The build now copies the `vcruntime140*.dll` Nuitka already places next to
  `run.exe` into the broker's own directory (Windows checks an exe's own dir first), with a build-gate
  assert so a future Mosquitto dep-set change is caught on the builder, not a bench.

## v1.19.0 — 2026-09-14

**Config → Barcode: a generic, operator-editable barcode structure replaces the old
prefix/fixed acquisition strategy (MINOR).**

The old `runs.acquisition.barcode.strategy` (`prefix` = first N chars are the recipe id,
`fixed` = barcode is just a serial, always run one hardcoded recipe) had no operator UI —
it was edited by hand in `app.json` — and couldn't express a barcode made of several
distinct fields at fixed positions.

- **New:** Config → Barcode page. Define the barcode's total length, its named parts
  (each an offset + length), which part is the recipe-id part, and whether barcode
  acquisition is enabled at all — all operator-editable (`CONFIG.EDIT`), same pattern as
  the existing Shifts page. Persisted as a single `barcode_config` DB record via
  `GET`/`PUT /config/barcode`.
- The Start dialog's Barcode/Recipe tab picker is gone — the popup now shows exactly one
  thing, driven by the Barcode page's enabled flag: a serial-number field (recipe
  auto-resolved from the configured recipe-id part) when enabled, or a recipe dropdown
  when not.
- `runs` module delegates recipe-id resolution to the new `config.resolve_recipe_from_barcode`
  contract method (a soft cross-module call, mirroring the existing `_delegate_reset`/
  `_python_test` pattern — no hard `contract_dependencies` edge, since module activation
  has no topological sort and `runs` activates before `config`).
- **Removed:** `modules/runs/acquisition.py`'s `resolve_recipe_id` (prefix/fixed
  strategies), the `/runs/acquisition` route, and `runs.config.schema.json`'s
  `acquisition.*` properties. `runs`'s `contract_version` bumps `1` → `2`.
- **Migration:** an app.json that still sets `acquisition.*` under the `runs` module config
  is not rejected (`additionalProperties: true`) — it's just silently inert now. Configure
  Config → Barcode instead.

## v1.18.2 — 2026-09-12

**A crashed step reported PASS with zero measurements instead of FAIL (PATCH).**

In `controller/controller/sequencer.py` `Sequencer._attempt()`: when a leaf step's
`handler.execute()` raised (`StepFailed` or any other `Exception`), the except blocks
correctly built a FAIL result — but the non-composite branch right after unconditionally
recomputed status from `results.step_status(result.measurements)` and overwrote it. A
crashed step has zero measurements, and `step_status()`'s documented "an empty list is
PASS" rule — correct for a handler that legitimately returned nothing to check — silently
clobbered the exception-forced FAIL back to PASS before `step-completed` ever emitted it.
This directly contradicted `results.py`'s own stated invariant ("structurally impossible
to report PASS over a failed measurement") and PRINCIPLES.md's "failures must be loud and
structured, never bare exceptions" — the blind spot was exactly a step that failed
*before* producing any measurement. A second symptom stacked on top: with zero
measurements, the `test-result` emit loop never fires either, so a downstream consumer
that only renders `test-result` events (e.g. an app's `run_sim.py` printer) sees nothing
at all for that step, not even a FAIL row — the `step-completed` event's `message` field
was already correct, this just went unseen by anything not watching that event.

- **Fix:** track whether the attempt took the exception path (`crashed`); the
  measurements-based `step_status()` computation now only applies when `execute()`
  returned normally — it can never override a status already forced to FAIL by a raised
  exception. The composite branch (`status = result.status`, trusting the handler's own
  aggregated verdict) is unaffected.
- Tests: `controller/tester/test_c3_sequencer.py` +2 — a leaf step type whose `execute()`
  raises a plain `Exception`, and one that raises `StepFailed` (both except paths), each
  asserting `step-completed.status == FAIL`, `measurement_count == 0`, the run verdict
  `FAIL`, and the exception message present. Verified both fail on the pre-fix code
  (reproducing PASS with 0 measurements exactly as reported) and pass after.

## v1.18.1 — 2026-09-11

**Backend no longer opens a second connection to a python-owned instrument (PATCH).**

Found on a real bench (Okaya, ITECH IT7300 AC source over VISA `...::SOCKET`, single-client
— accepts exactly one session). Under a supervised Python controller, the backend's own
variable engine has always independently built and connected its own `instrumentlib`
instances from the same `owner=python` Config → Instruments records the controller
subprocess already connects to. Invisible for a multi-client instrument; for a
single-client one the loser of that race gets refused and its `InstrumentBase.state`
sticks at `disconnected` **forever** (a failed *initial* connect never retries) — Config →
Instruments / Maintenance then falsely shows a fully working instrument as permanently
broken.

- **Fix:** when `controller.kind=="python"`, the backend never opens its own connection to
  an `owner=python` instrument any more. It reaches each one through the supervised
  controller's own live connection instead — exactly how LabVIEW already does — via two
  new bridge verbs, `instrument.call` (any method + args, generalizing `instrument.test`'s
  identify()-only pattern) and `instrument.status` (live per-instance state).
  `InstanceRegistry.build()` gains a proxy mode (a new `ProxiedInstrument` that never opens
  a transport); under `controller.kind=="labview"` nothing changes (no controller
  subprocess exists to proxy through, and this path was never racy).
- Confirmed by tracing the codebase, not assumed: recipe execution (`TEST.RUN`) never
  touches this registry at all — it drives everything through `run.start`/`run.abort` to
  the controller's own, separate `StationVariables`. So backend-side instrument access
  (Maintenance's Variables panel, the Instrument Test Bench) was always manual/UI-only,
  and proxying it costs nothing on any latency-sensitive path.
- `GET /variables/instances` now does one live `instrument.status` poll before answering,
  instead of trusting a cached flag that could never un-stick itself — strictly more
  honest than before, and self-heals the moment the controller comes up.
- `CoreServices` gains a `controller_kind` field (mirrors the existing `stations`/
  `station` topology fields) so a module can tell without a new contract method.
- Docs: `PYTHON_CONTROLLER.md` §7 (the two new verbs + the ownership invariant),
  `LABVIEW_BRIDGE.md` §5.1, `docs/contracts/CONFIG.md`, `INSTRUMENT_LIBRARY.md` §0,
  `ARCHITECTURE.md`, `docs/help/dev/instrument-library.md`.

Tests: +19 backend (`tests/test_variables_proxy.py` + 2 in `modules/variables/tester/`),
+7 controller (`tester/test_instrument_call.py`). Full suites green: 489 backend passed,
115 controller passed.

## v1.18.0 — 2026-09-10

**System Blueprint — author an app's I/O from a spreadsheet (MINOR).**

A new app-authoring aid: an Excel workbook a test engineer fills in to declare one
application's I/O system — its instruments and every input/output signal with the address
relative to an instrument — and a deterministic generator that turns it into the framework's
canonical artifacts. It defines the system's topology, never the tests.

- **Tooling** `backend/tools/blueprint/` (`python -m tools.blueprint make-template|generate`):
  builds the blank workbook (the generator script is the git source of truth; the `.xlsx` is
  generated on demand), and generates/reconciles `app/<name>/maps/<station>.json` (the
  controller-side variable map), a `maps/.blueprint.lock.json` tag ledger, `docs/INSTRUMENTS.md`
  (the Config → Instruments checklist + a paste-ready `controller.json` `instances` block),
  `docs/MULTIPLEXING.md`, and a `blueprint-report.md`.
- **Stable per-row `tag`** is the reconcile key: a fuller sheet supplied later updates in place
  (fills TBDs, renames/moves by tag, adds new) instead of clobbering work; a signal with no
  read/write is kept pending; a signal dropped from the sheet is kept-and-warned (`--prune` to
  delete). Validation vocabularies (capability methods, transports) are read live from the
  framework code, so the template never drifts from what the variable engine accepts.
- **Multiplexing** (one shared reader scanned via relays) is modelled as a composite driver:
  each scan point is an ordinary signal on the composite instrument, and the relay switching is
  captured on a Multiplexing sheet that becomes the `create-instrument-library` build spec — a
  digital output that only steers the mux is a selector element, not a signal.
- New **`system-blueprint`** skill (both `.claude/skills/` and `plugins/tmf-tools/` copies);
  `new-test-app` points at it. New `docs/SYSTEM_BLUEPRINT.md` contract + dev help page.
- `openpyxl` added to the `dev` extra (authoring-time only; not a station runtime dependency).

## v1.17.1 — 2026-09-09

Data-durability + UX fixes on the update path, found in a real frozen-station update. PATCH.

- **CRITICAL — recipes were written inside `run.dist` and orphaned on every update.**
  `FilesystemRecipe` resolved its store `root` (default `"data/recipes"`) relative to the
  process CWD, which for a frozen station is `run.dist` — the unit the launcher renames into
  `data/backups/bak-*` on a swap. Result: the operator's recipes (authored in-app, no other
  copy) vanished from the UI on the next update. Fixed with a new
  `core.services.config.resolve_state_path()` that resolves relative config paths against the
  **external deploy root** (`TMF_STATE_DIR` when frozen, `backend/` in source — dev/test layout
  unchanged), plus `migrate_cwd_state()` which, on module construct, does a one-time copy of a
  pre-fix build's `run.dist/data/recipes` to the external root with a loud diag warning so
  existing stations recover their recipes on upgrade.
- **Same bug, lower severity — report outbox, report folder sinks, MES folder dirs.** The
  report **outbox** (`outbox_path`, default `data/report_outbox.sqlite` — holds reports queued
  for the professional DB but not yet forwarded) had the identical CWD-relative default and is
  now resolved + migrated the same way. The result-routed **folder sinks**
  (`report.sinks[].path`) and the **MES folder** handoff dirs
  (`mes.folder.upstream_dir`/`downstream_dir`) also resolve through `resolve_state_path()` now,
  but without auto-migration — they are a redundant export / transient per-serial interlock,
  not operator-facing report data (that lives in the pro DB / `tmf.sqlite`, which was never
  affected — the earlier "reports destroyed" claim was overstated).
- **Updates page sat on the stale pre-relaunch view forever.** `relaunch()` / `rollback()` in
  `UpdatesConfig.tsx` posted the request and showed a static "will reconnect shortly" line with
  nothing behind it — the operator had to close and reopen the whole app to see the new version.
  Now it polls `/healthz` (2 s interval, ~90 s budget) after the POST and calls `refresh()` once
  the station answers, showing a real "waiting for it to come back" spinner that resolves into
  the post-relaunch state; a timeout shows a "reload manually" error.

## v1.17.0 — 2026-09-06

Two independent capabilities, both from real pain cutting fork releases on GitHub Free. MINOR
(additive; existing deployments unchanged).

- **Generic local release-cutting script — `deploy/cut-release.ps1.template`.** GitHub Actions
  cache is scoped per-ref: a `.nuitka-cache` saved on one `app-v*` tag is unreachable from the
  next, and nothing runs the Nuitka build on the default branch to seed the fallback scope — so
  **every** templated `release.yml` build is cold, ~45 min ≈ 90 GitHub-Free minutes per release
  (Windows bills 2×). The new script runs the identical steps (version guard → tests → vendor
  Mosquitto → Nuitka → sign `.ksupdate` → WebView2 + `setup.exe` → `gh release create` with the
  same four assets) on a developer's machine with a **persistent** `NUITKA_CACHE_DIR`, warm after
  the first build. `new-test-app` renders it per-fork (`@@APP_SLUG@@`) alongside — not replacing —
  `release.yml`; a fork that adopts it retargets its own `release.yml` to `on: workflow_dispatch:`.
  It also **pushes the `app-v<ver>` tag before the build** as a race lock, and both it and
  `release.yml`'s guard now reject a version that isn't strictly semver-greater than the latest
  published `app-v*` tag (the old `tag == VERSION` check passed even for a regression). New
  `CONTRIBUTING.md.template` documents the local toolchain + the app/framework boundary. Comment
  block atop `docs/templates/release.yml` explains the cache limitation and points at the script.
- **`updates.station_mode` — restrict a station to one update source.** `DEPLOY_STATION.md`
  describes two update paths (online check/download vs. USB `install-file`) but nothing enforced
  the split. New `updates.station_mode` enum in `app.schema.json`: `"online"` (default) →
  `/update/check` + `/update/download` reachable, `/update/install-file` → **409**; `"air_gapped"`
  → the reverse. New `StationModeBlocked` exception (sibling of `AmcRequired`), raised by
  `UpdateService.check/download/install_from_file`, mapped to HTTP 409 in `core/app.py`.
  `GET /update/offers` now returns `station_mode`; the Updates page hides the disallowed half with
  an explanation. Default `"online"` = zero migration. Independent of `allow_unverified` (that's
  trust; this is source).

## v1.16.3 — 2026-09-06

Both bugs reproduced live end-to-end against a real installed frozen station (`okaya_transformer`,
app v1.0.3 on framework v1.16.2) actually attempting an in-app update apply. PATCH — but the first
is safety-relevant: every app-track fork's in-app update-apply was non-functional and leaked a live
controller per attempt.

- **App-track relaunch swap ALWAYS failed, and leaked an orphaned controller each time.** On an
  app-track build the backend (`run.exe`) spawns `run.exe --controller` as its **own** child. The
  update relaunch/rollback endpoints exit the backend with a hard `os._exit(42)` that skips the
  lifespan teardown — so that controller child was never stopped: it stayed alive across relaunch
  generations, kept its image inside `run.dist` open (so `launcher.py`'s `live → .bak` rename
  failed with `WinError 32` **every single time**), and `reconcile()` then silently relaunched the
  OLD version with the Updates page stuck on `relaunch_requested` forever. Repro left 4 stray live
  controller processes after 4 relaunch attempts — and more than one process driving instrument
  I/O is a bench hazard, not just wasted memory. Fixed in depth: (1) the relaunch/rollback
  endpoints (`core/app.py` `_exit_relaunch`) now stop the controller — graceful `CTRL_BREAK` →
  every instrument to safe state → confirmed dead, hard `taskkill /T` on the whole tree on
  timeout — **before** scheduling the exit; `ControllerSupervisor.stop()` returns that as a bool.
  (2) `launcher.py` runs each backend generation in a Windows **Job Object** with
  `KILL_ON_JOB_CLOSE` (`_WinJob`) and terminates it after `proc.wait()`, so any descendant that
  outlived the backend is gone before the swap, unconditionally. (3) the swap rename retries with
  backoff (`_rename_with_retry`) for the brief window a just-exited process can still hold a handle.
  (4) a swap that still fails writes `data/last_swap_error.json`; `/update/status` surfaces
  `swap_failed` and the Updates page shows the error + strike count instead of looping silently.
  New tests: `stop()` confirms a real child tree is dead; the relaunch endpoint stops the
  controller before `os._exit`; rename retry + failure-breadcrumb; status surfacing.
- **Backend `run.exe` popped a visible console window on every spawn (every relaunch).** `run.exe`
  is a console-subsystem exe and `launcher.py`'s `Supervisor` spawned it with only
  `CREATE_NEW_PROCESS_GROUP`; launched from the windowed `run_station.exe` (no console of its own)
  Windows allocated a fresh console window each time — "one more command prompt window" on every
  relaunch of a kiosk station. Fixed: `CREATE_NO_WINDOW` bitwise-OR'd into the flags at that spawn
  site only (running `run.exe` from a terminal still gets a console), and the same treatment for
  the frozen `run.exe --controller` child in `core/services/controller_supervisor.py` (its stdout
  is already piped into diagnostics, so the console showed nothing anyway).
## v1.16.2 — 2026-09-06

Two bugs found running the update pipeline for real against a live GitHub Releases repo. PATCH.

- **`UpdateService.check()` never compared versions — "Update available" fired for the CURRENT
  version too.** Reproduced live: a station on app v1.0.2, checking a repo whose latest release
  was ALSO app-v1.0.2, showed "Update available: app-v1.0.2" for the exact version already
  installed. `check()` only asked "does the latest release have a `.ksupdate` asset" — the real
  applicability gate (`resolve()`'s `_semver()` comparison) only ran later, at `download()`/
  `ingest()` time, AFTER the misleading banner had already shown. Fixed: `check()` now compares
  the release tag's version (stripping the `app-v`/`v` prefix) against the installed baseline —
  same baseline `resolve()` uses — before ever calling it "available." Every station's Updates
  page had been showing false positives for anyone actually current. 4 new tests, including the
  exact reported scenario (tag equals installed version → no offer).
- **`_WEBVIEW_NOFOLLOW` excluding `webview.platforms.win32` is NOT stable across Nuitka/pywebview
  version combinations.** v1.15.1 added `win32` to fix a real conflict on one machine; excluding
  it broke the build on another (confirmed empirically, in OPPOSITE directions, on two real
  Windows boxes running the very same Nuitka 4.1.3 — the difference is elsewhere in the toolchain,
  not something a static list can track). A hardcoded list can only ever be tuned for the machine
  it was tested against. Fixed properly instead of flip-flopping the list again: `build_run_station_exe()`
  now retries adaptively — start with the four submodules that are non-Windows on every version
  (`android`/`cocoa`/`gtk`/`qt`), and if Nuitka's own FATAL line names one more (e.g. `win32`),
  add exactly that name and try again, up to a few rounds. This is the CI check the original ask
  wanted ("attempts the Nuitka compile, not just static review of the flag list") — release.yml's
  existing real build IS that check, now self-correcting instead of needing a human to re-tune the
  list every time a fork's toolchain disagrees with the last one. Verified live end-to-end on this
  machine: round 1 hits the win32 conflict, round 2 (win32 added) compiles clean, smoke-tests OK.
- **Found while re-verifying the above: the runtime smoke test itself had a false-positive bug.**
  `_verify_run_station_exe`'s `/healthz` probe didn't check WHO was answering — a stray station a
  dev already had running on :8000 answered the probe instead of the freshly-built (and, in this
  reproduction, non-booting — no `run.dist` present) exe, and the smoke test reported "verified"
  regardless. Fixed: refuse to run the check at all if anything already answers `/healthz` before
  the exe is even spawned. 2 new tests cover both branches (occupied port aborts without spawning;
  free port proceeds to spawn).

## v1.16.1 — 2026-09-06

- **"Manage users" added to the account dropdown** (top-right avatar menu), alongside Log out —
  a second path to the same `/users` page Administration → Users already opens. Gated on the same
  `AUTH.MANAGE_USERS` permission as the sidebar entry, so visibility is identical between the two.

## v1.16.0 — 2026-09-06

Nav simplification + a real bug fix hiding behind it: the `daq` module was LabVIEW-only and
inert under the Python controller, but its `/instruments/values/ws` live-values relay is
controller-agnostic and Runs/Maintenance depend on it. MINOR — no locked contract broke (an
existing fork's `app.json` still listing `daq` degrades gracefully, "not registered," not a
crash) but a LabVIEW-controller fork that actively used DAQ streaming loses that capability on
merge; read this before pulling the change in.

- **`daq` module removed entirely** (backend + frontend). It bundled two unrelated things: (1)
  LabVIEW analog/digital signal streaming (`ai`/`di`), genuinely dead under `controller.kind:
  python`, and (2) a generic live-station-variable-values relay (`/instruments/values/ws`,
  subscribing `value/#`) used by `Runs`/`Maintenance`'s live-values panel — NOT LabVIEW-specific,
  since the Python controller retained-publishes `value/{name}` on every step read/write too.
  (2) is migrated into the `variables` module (which already owned the identically-pathed, and
  previously **colliding**, `GET/PUT /variables/{name}/value` routes — same URL, two different
  handlers registered by two different modules); (1) plus the `Daq.tsx` screen, its nav entry,
  `Sparkline.tsx` (its only consumer), the `docs/contracts/daq.md` contract, the
  `docs/HOWTO_TEST_DAQ_WITH_LABVIEW.md` guide, and the LabVIEW-hardware-only
  `tools/check_phase1.py` acceptance script are deleted outright.
- **"Test Bench" nav entry + `/instruments/test` route removed** — `Maintenance.tsx` already
  embeds the identical `InstrumentControlPanel` for `super_admin`; the standalone page was a
  redundant second mount of the same component, reachable by no one who couldn't already see it
  in Maintenance. `InstrumentTestBench.tsx` deleted; its still-relevant help content merged into
  `docs/help/user/maintenance.md` as a subsection.
- **"Variable Map" dropped from the nav** — the `test-step-authoring`/`add-bench-test` skills
  author bindings directly, so the manual editor sees little use. Route, backend, and the skill's
  automation are untouched; a super_admin can still reach `/config/variables` directly.

## v1.15.2 — 2026-09-06

- **Permissions page couldn't grant `DIAGNOSTICS.PURGE`.** It has gated `DELETE
  /logs/{errors,actions}` since 2026-06-05 but was never added to `permissions_catalog.py` —
  invisible to the role matrix (worked for `super_admin` only, via the `DIAGNOSTICS.*` wildcard;
  no other role could be granted it). Added. New `test_permissions_catalog.py` scans every
  `require_permission`/`permission_granted` call site and fails if one isn't cataloged, so the
  next module can't reintroduce this gap silently — verified it actually catches the regression
  (reverted the fix, test failed naming the exact gap; restored, green).

## v1.15.1 — 2026-09-06

`build_release.py --track app` could not freeze `run_station.exe` on an MSVC-less builder, a
broken build could still be packaged into a shippable installer, and a failed update check
looked identical to "you are up to date." PATCH.

- **`run_station.exe` couldn't locate `run.dist` when frozen (broke EVERY frozen station, not just
  the build).** In a Nuitka **onefile** exe, `__file__` resolves to the temp extraction dir, not the
  exe's real location — so `ROOT` (and thus `RUN_DIST`) pointed into `…\Temp\onefile_XXXX_…\` and the
  launcher aborted at startup ("run.dist not found"). Fixed: compute `FROZEN` first and use
  `sys.argv[0]` (the invoked exe's own path) for `ROOT` when frozen. Verified against a real onefile
  build: the error message now names the exe's actual directory.
- **Nuitka plugin conflict killed the compile** (`FATAL: Conflict between user and plugin decision
  for module 'webview.platforms.android'`, then `'...win32'` once the first four were excluded).
  Force-including the whole `webview` package pulled back in platform backends Nuitka's own pywebview
  plugin had already excluded. Fixed with
  `--nofollow-import-to=webview.platforms.{android,cocoa,gtk,qt,win32}` (matching the plugin's own
  Windows allow-list: winforms/edgechromium/edgehtml/mshtml/cef) alongside `--include-package=webview`.
  Verified end-to-end: `build_release.py`'s Nuitka invocation now completes and produces a working exe
  against a real pywebview 6.2.1 install.
- **Onefile shipped uncompressed** without `zstandard`. Added it (+ `pywebview`) to the backend's
  `release` extra so `pip install -e "backend[release]"` alone covers everything the build needs.
  Verified: onefile payload compressed ~24% smaller with it present.
- **Fail-soft + a real runtime gate.** `build_run_station_exe()` now actually **runs** the compiled
  exe (`--no-window` from a real station root) and asserts it reaches `/healthz` before calling it
  good — a compile that produces a broken exe (the historical MSVC-less zig/clang failure mode) is
  caught instead of shipped. A compile or smoke-test failure no longer aborts the whole release: it
  WARNs, removes the broken exe, and `build_release.py` exits a **distinct code (3)** — `run.dist` +
  the `.zip`/`.ksupdate` (the in-app update artifact) still get built either way, since only the
  offline `setup.exe` needs `run_station.exe`. `release.yml` checks that exit code and publishes the
  release without `run_station.exe`/`setup.exe` on 3, instead of failing the whole workflow.
- **A broken/stale build could still be packaged into a shippable `setup.exe`.** Before the fail-soft
  fix above, a `build_run_station_exe()` failure raised `SystemExit` *before* `build_release.py`
  reached the step that writes `RELEASE.json` into `run.dist` — leaving a `release-build/` on disk
  with run.dist present but no version manifest at all. `deploy/build-installer.ps1` only checked
  that `run.dist`/`run_station.exe` *existed*, not that the build was *complete and current* — so it
  happily packaged that partial build (or an older `release-build/` left over from a previous
  successful run, now stale against a bumped `app/<slug>/VERSION`) into a `setup.exe` that shipped
  with `app_version()` permanently returning `None`, making every future "Check for updates"
  comparison meaningless from first boot. Fixed: `build-installer.ps1` now refuses to package unless
  `release-build/RELEASE.json` exists, `track == "app"`, and its `version` matches
  `app/<slug>/VERSION` — with a clear "re-run build_release.py" error otherwise. (The ordering fix
  above already prevents the original *incomplete-build* failure mode from recurring; this adds the
  same guard for a hard `build_backend()` failure or a forgotten rebuild after a version bump.)
- **A failed update check looked identical to "you are up to date."** `UpdateService.check()` is
  deliberately network-tolerant — on any GitHub error (no network, or a private repo rejecting an
  empty/invalid token) it returns 200 with `available: null` and `error` set, not an exception. The
  Updates page ignored `error` entirely and showed the same neutral "No update available — you are up
  to date" message either way, so an operator had no way to tell "genuinely current" apart from "the
  check is broken" (reproduced for real: an empty `github_token` against a private repo silently
  reported "up to date"). Fixed: `error` now surfaces as a distinct, actionable failure message
  ("Update check failed: … — verify updates.github_repo/github_token…") in the page's error state,
  not the neutral info banner.
- `deploy/build-installer.ps1`'s "missing run_station.exe" error explains why (fail-soft) and how to
  fix it (build where the tested MSVC toolchain is — e.g. the release CI runner — or install VS Build
  Tools locally). Documented in `docs/DEPLOY_STATION.md` §1.

## v1.15.0 — 2026-09-05

Desktop-station polish: a real app icon, working report export in the native window, an actionable
Dashboard, and update-page clarity. MINOR.

- **Dashboard redesign.** The old "loaded modules" grid (raw activation-gate dump, no operator value)
  is replaced with an at-a-glance ops view: an **attention band** that surfaces only what needs a
  human — disconnected instruments, an offline station bridge, an unconfigured report database,
  modules skipped for config/license reasons, and (super_admin) an available application update —
  with a calm "All systems normal" strip when there is nothing to act on. Below it, a **7-day KPI
  band** (runs, yield, units, first-pass yield, avg cycle) and a **pass/fail trend chart**
  (`/reports/analytics/dashboard`), plus a **live instrument snapshot** reading real connection state
  from the variable engine (`/variables/instances`) instead of a static list.
- **Native window app icon.** `station.py` / `run_station.py` now set the pywebview window title-bar
  icon via `webview.start(icon=…)`, and `build_release.py` embeds it into `run_station.exe`
  (`--windows-icon-from-ico`) so the taskbar icon is right before the window opens. Added
  `frontend/public/favicon.ico` (multi-res, generated from `favicon.svg`) — a fork's own favicon is
  used automatically.
- **Report export in the desktop window.** `Reports` CSV/JSON export produced nothing visible in the
  native window (a browser blob-download has no flyout and an unknown location under WebView2). Export
  now **saves server-side to the station PC's Downloads folder** (`?save=true` on
  `/reports/full/export` and `/reports/{id}/export`) and a green banner shows the **exact path**
  (`Downloads\reports-full-<date>-<time>.csv`); files are timestamped so nothing is overwritten.
  Errors are surfaced instead of silently swallowed.
- **Updates page clarity.** Shows the **application** version prominently beside the framework
  version, and states that "Check for application updates" polls this app's own release line only —
  never framework updates.
- **new-test-app skill:** backend deps install now includes the `desktop` extra (pywebview) so
  `python station.py` gets a native window instead of falling back to the browser.

## v1.14.0 — 2026-09-04

Fully-offline frozen station: a client PC needs **zero online setup** and **zero post-install steps
except configuring instruments**. Double-click the desktop shortcut → the app opens fullscreen. MINOR.

- **Frozen windowed launcher — no system Python, no pip on the client.** The launcher's supervision
  loop is now importable (`launcher.Supervisor` / `launcher.supervise`), and `run_station.py` runs it
  **in-process on a thread** instead of shelling `[python, run.dist/launcher.py]`. `build_release.py
  --track app` Nuitka-compiles `run_station.py` into a standalone **`run_station.exe`** (bundles
  pywebview + the `launcher` module) placed in the station root **beside `run.dist`** (survives the
  updater's run.dist swap). `run.exe` is still spawned as the swappable backend child; the full
  exit-42 / staged-swap / rollback loop is unchanged (Supervisor spawns run.exe in its own process
  group and shuts it down with a graceful CTRL_BREAK on window close).
- **Vendored Mosquitto — no broker install, no service, no admin.** `build_release.py --track app`
  copies `deploy/vendor/mosquitto/win64/` **into** `run.dist/vendor/mosquitto/win64/`, so the frozen
  station starts its own loopback broker. `run_station` now launches it with `-c mosquitto.conf`
  (Mosquitto 2.x refuses anonymous clients without a config). Because it rides inside run.dist, every
  in-app update carries it and it survives swaps.
- **Offline `setup.exe` first-install.** New `deploy/installer.iss.template` + `deploy/build-installer.ps1`
  render + compile a per-fork Inno installer that bundles `run.dist` (incl. the vendored broker),
  `run_station.exe`, and the offline WebView2 standalone runtime (the one true OS dependency; a no-op
  when present). It lets the operator pick a **user-writable** install dir (not Program Files, so the
  updater can rename run.dist), grants `Users:Modify`, and drops Desktop + Start-Menu shortcuts to
  `run_station.exe --fullscreen`. The only post-install task is Config → Instruments.
- **Air-gapped in-app updates from USB.** New `POST /update/install-file` (+ Updates page "Install
  from file") stages an update from local `.ksupdate` + `.zip` paths through the **same** signature +
  `full_artifact_hash` verify and stage → swap → rollback pipeline as the online path — only the
  source differs. `_materialize` refactored to share `_stage_zip_bytes` with the new path.
- **CI: four release assets.** `docs/templates/release.yml` now vendors Mosquitto, builds
  `run_station.exe`, and builds the offline `setup.exe` (Inno + bundled WebView2), publishing
  `<slug>-<ver>.zip`, `.ksupdate`, `run_station.exe`, and `<AppShort>-Setup-<ver>.exe`.
- **install-station.ps1 Store-alias fix.** The Python probe no longer trusts `Get-Command python`
  (the Microsoft Store `python.exe` alias is a stub) — it checks `py.exe` / `sys.executable` and
  installs a real interpreter on a bare PC. The script is now the scriptable/headless **fallback**;
  the offline `setup.exe` is the primary first-install path.
- Docs + both `new-test-app` skill copies updated (DEPLOY_STATION, UPDATES §E-bis endpoint + air-gap
  row, deploy/README). **Update caveat:** the in-app updater swaps only `run.dist`; a release that
  changes `run_station.exe` must be delivered by re-running `setup.exe` (flagged in the CHANGELOG).

## v1.13.0 — 2026-09-04

Release/CI tooling so a fork cuts a release cleanly + fast, plus a Windows data-integrity fix in the
debug flight-recorder. MINOR.

- **App release tags no longer collide with inherited framework tags.** A fork inherits every
  framework `v*` tag, so the app's own v1.0.0/v1.1.0/… line was unusable. `docs/templates/release.yml`
  now triggers on **`app-v*`** and derives the version with `${GITHUB_REF_NAME#app-v}` throughout
  (guard, sign, notes, publish); asset names stay plain `<slug>-<ver>.zip`/`.ksupdate`. The in-app
  updater reads the version from the `.ksupdate` **manifest**, never the tag, so the prefix is
  invisible to clients. Docs (APP_REPO, UPDATES §10.3, DEPLOY_STATION) + both `new-test-app` skill
  copies now say to tag `app-v<version>` and push **only that tag** — never `git push --tags`, which
  would push all inherited framework tags and fire the workflow once per tag.
- **debug_server rolling sink: same-millisecond rotation no longer crashes or loses data.**
  `RollingSink._rotate()` named rotated files `debug-<ms>.jsonl`; two rotations in one millisecond
  produced the same name → `FileExistsError [WinError 183]` on Windows (rename won't overwrite) and a
  **silent overwrite** of the earlier file on POSIX (data loss with no error — why Linux CI never
  caught it). Names are now collision-proof (`debug-<ms>-<n>.jsonl`, counter bumped until free,
  checking both the `.jsonl` and compressed `.jsonl.gz` forms); `_rolled()` sorts with the name as a
  tiebreak so same-ms files stay ordered. New test asserts no loss/crash across 40 forced same-ms
  rotations. It was the only `.rename(` in `debug_server`.
- **Framework CI already covers Windows** (the `backend` job is `windows-latest`, and pytest
  `testpaths` includes `debug_server`), so the new test guards this class of Windows-only regression
  at every framework push — the exact bug an app's `windows-latest` release build would otherwise
  hit first. No CI change needed.
- **Release CI caches Nuitka.** The template adds `setup-python` pip caching + an `actions/cache@v4`
  step for `NUITKA_CACHE_DIR`, keyed on the framework version — a framework bump recompiles clean, an
  app-only change hits the cache (clcache warms the rest), turning a cold ~15–20 min build into an
  incremental one.

## v1.12.0 — 2026-09-04

Client deployment + in-app updates are now an inherited, first-class capability, and the published
artifact is a **complete** app. MINOR.

The update runtime already existed (checker, journalled swap, rollback, signer); what was missing was
the glue every fork needs to actually deploy and update a client — plus a gap where the shipped `.zip`
was not self-contained.

- **One-time station bootstrap.** New `deploy/install-station.ps1 -Product <slug> -Repo <owner>/<repo>
  [-Token] [-Channel] [-InstallDir]` — idempotent: ensures system Python, installs the Mosquitto
  broker (`winget EclipseFoundation.Mosquitto`), `pip install pywebview`, downloads the latest
  app-track Release's `<slug>-<ver>.zip` via the **private-repo** asset API, verifies its sha256
  against the `.ksupdate` manifest's `full_artifact_hash`, extracts to `<InstallDir>\run.dist`, drops
  `run_station.py` beside it, and launches the station. GitHub Releases delivers *updates*; this
  delivers the *first* install.
- **Artifact completeness.** The build now copies `frontend/` **and** `docs/` **into `run.dist`**
  (the swap unit that `package_artifact` zips), and the SPA + help resolvers prefer that location
  (`spa.py`, `help/catalog.py`). Before this, the UI was served from the deploy root and docs from the
  source tree — outside the zip — so an install-from-zip had no UI and an update never refreshed the
  help. Now the `.zip` carries the UI, the in-app help, the app definition, and the drivers; one swap
  refreshes all of it, **including a fork's custom screen overrides** (compiled into its own
  `frontend/dist`). Verified on a frozen build: `GET /` serves the SPA from `run.dist\frontend`,
  `/help/index` lists 54 pages read from `run.dist\docs`, and the published `.zip` contains both.
- **Pre-wired update config.** `app.example.json` ships a commented-style `updates` block
  (`github_repo`, `github_token:""`, `channel`, `allow_unverified`) and the schema now permits
  `channel` + `allow_unverified` (the latter was already read by `app.py` — a latent schema gap).
  `new-test-app` sets `updates.github_repo` to the fork's origin and scaffolds `release.yml`.
- **Dev-untrusted updates, gated.** Pre-Keystation there is no signing ceremony, so `release.yml`
  dev-signs the `.ksupdate` when no `KS_INTERMEDIATE_SEED`/`_CERT` secrets are set (manifest exists,
  flagged `verified:false`), and a client installs an untrusted release **only** when
  `updates.allow_unverified: true` (shown UNTRUSTED in the UI). Standing up Keystation = add the real
  secrets + flip the switch to false; no other change.
- **Docs + skill.** New `docs/DEPLOY_STATION.md` (first install → cut a release → update a client →
  trust → read-token security), cross-linked from RUNNING/APP_REPO/SECURE_DISTRIBUTION; `release.yml`
  aligned (three assets, optional secrets); both copies of the `new-test-app` skill wire the `updates`
  block + `release.yml` so a fork is deploy- and update-ready on day one.

## v1.11.0 — 2026-09-03

App builds work on MSVC-less builders: one exe, `run.exe` also runs the controller. MINOR.

The v1.10.x app build compiled a SEPARATE controller.exe. On a Windows machine without MSVC, Nuitka
falls back to its bundled **zig** backend, which reliably bundles the pure-Python stdlib only for
LARGE import graphs — the lean controller graph deterministically produced a stdlib-less exe that
crashed at startup (`Failed to import encodings`). No Nuitka flag fixes this reliably.

- **One exe.** `run.py` now dual-dispatches: `run.exe --controller <config>` runs the controller
  (`controller.__main__.main`) instead of uvicorn. The supervisor spawns that in a frozen build; the
  separate `build_controller` step + `controller.dist/` are gone. The controller reuses `run.exe`'s
  stdlib (its large graph always pulls it in), so it works on **every** backend incl. zig — no MSVC
  required just to bundle the stdlib. Bonus: ~half the app-build time (one compile) and a smaller
  artifact (~77 MB vs ~113 MB).
- **Build gate**, unchanged in spirit: after the backend compile, `build_release` launches
  `run.exe --controller` with the app's step packages + an unreachable broker and FAILS the build
  unless it reaches `instruments:` with no crash. A controller that can't start never ships.
- **`--mingw64` now errors clearly on Python 3.13+** (Nuitka rejects it and ignores an external
  winlibs gcc) instead of a cryptic FATAL. MSVC + clcache stays the default; MSVC is the tested
  backend (docs note the zig fallback is covered by the gate).
- Verified end-to-end: single-exe app build, `run.exe --controller` comes up `online` (`/readyz`),
  loads the app step package, no encodings/`getsource` crash.

## v1.10.2 — 2026-09-02

Fix: the frozen controller.exe couldn't start (app couldn't run its test sequence). PATCH.

Two frozen-only bugs in the v1.10.0 app-track build, both of which left a frozen app booting the UI
shell but unable to run the controller (the exact FAIL v1.10.0 claimed to prevent; masked on this
repo's MSVC backend, exposed on the zig backend an MSVC-less builder gets):

- **stdlib not bundled → `Fatal Python error: Failed to import encodings`.** `build_controller`
  pointed Nuitka at the package's `__main__.py`; Nuitka then skips the pure-Python stdlib. Now it
  compiles a plain SCRIPT entry (`controller/run_controller.py`, mirroring `backend/run.py`), which
  bundles the full stdlib on every backend (MSVC / MinGW / zig).
- **`inspect.getsource` in the conformance re-check → `OSError: could not get source code`.** The
  step-type gate re-run at controller startup inspected handler source, which a compiled build has
  no access to. `conformance.check_handler` now skips the source rules when source is unavailable
  (it is an authoring/CI gate that already ran before compilation).

- **`build_controller` now GATES the build**: it launches the frozen `controller.exe` with the app's
  step packages and an unreachable broker, and FAILS the whole build unless the controller completes
  startup (loads its packages, passes the conformance re-check, reaches `instruments:`) with no
  crash. A controller that can't start can never ship again — on any compiler.
- Verified end-to-end: the frozen controller reaches `controller up … online`, `/readyz` online, no
  encodings/`getsource` crash.

## v1.10.1 — 2026-09-02

Build: explicit compiler backend — MSVC + clcache default, MinGW opt-in. PATCH.

- `build_release.py` now selects the Nuitka compiler backend explicitly. **Default = MSVC (`cl`)
  + clcache**, an object cache: a WARM rebuild is near-instant — verified **1610/1614 C-file cache
  hits** (only changed files recompile). This is the "fast rebuild" path and needs no toolchain
  install (it's what Nuitka already auto-picked, now pinned so it can't drift).
- **`--mingw64`** opts into gcc + ccache for machines with a working MinGW. Nuitka's
  auto-downloaded gcc 15.2.0 ships a broken Windows SDK header (`psdk_inc/intrin-impl.h`) that fails
  the C compile on some setups, so it is opt-in (install a known-good MinGW, e.g. winlibs gcc 13.x).
- No change to build output; the first build on a machine is still a cold (cache-miss) full compile.

## v1.10.0 — 2026-09-02

`build_release.py --track app` produces a complete, runnable frozen app. MINOR.

- **The app-track build is now self-contained + runnable.** Alongside the compiled backend it
  compiles the **Python controller** (`run.dist/controller.dist/controller.exe`) and bundles the
  app **definition** (`app/<slug>/` controller.json + maps + specs) and copied `instrument_libs/`,
  all INSIDE `run.dist` (so an update swap carries the whole thing). The app's `step_type_packages`
  + `instrument_libs` are **compiled into both exes** (`--include-package(-data)`, discovered from
  `app/<slug>/controller.json`) so they load by name in the frozen build. A frozen app now runs its
  OWN test sequence — before, it booted only the framework UI shell and started no controller.
- **Site config is never bundled.** No `recipes/`, no instrument instances (IP/COM/port), no
  report/DB credentials — those stay in the external state (`STATE_ROOT/config` + DB), set on the
  bench. `--app-config` (default `backend/config/app.release.json`) ships a non-secret
  `config/app.example.json` (credentials stripped) so the app boots with its own branding + controller.
- **Fix (was silently broken):** the controller supervisor detected frozen builds via `sys.frozen`,
  which **Nuitka does not set** — so the bundled controller was never started under a Nuitka build.
  Now detects Nuitka (`__compiled__`); frozen `config_file` + `controller.dist` paths resolve
  against `run.dist`. The variables module registers `instrument_libs` via `find_spec` when it is
  compiled in (file absent).
- Docs: `SECURE_DISTRIBUTION.md` §5 (full layout), `RUNNING.md` (running a frozen app),
  `TEMPLATE.md` §4 (two-tier release + an app-build acceptance step).

## v1.9.5 — 2026-09-01

Fork-remote safety: framework remote is push-disabled and `origin` is required. PATCH.

- **`new-test-app` now push-disables the framework remote** — after `git remote rename origin
  upstream` it runs `git remote set-url --push upstream DISABLE`, so app commits can never be pushed
  to the framework repo, even from a Git GUI and even if `origin` is missing. A Git GUI derives a
  repo's identity from its remote, so a fork whose only remote is the framework showed up **as** the
  framework and offered to push the app's commits straight into it (hit on a real customer fork).
- **`origin` is now a required, first-class step**, not an optional "local trial" skip: create it
  with `gh repo create <org>/App_<Name> --private --source . --remote origin --push` (or prompt for
  the URL). Local-only forks are allowed only as a deliberate fallback with a loud Phase-6 warning to
  publish before opening in any Git GUI.
- Mirrored across both `new-test-app` skill copies (`.claude/skills/` + `plugins/tmf-tools/`),
  `docs/TEMPLATE.md` §2, `docs/APP_REPO.md`, and `docs/templates/APP_SETUP.md`.

## v1.9.4 — 2026-09-01

Report DB auto-create + drivers installed by default; interface skills. PATCH.

- **Report store auto-creates its database.** Configuring/testing a MySQL or SQL Server report
  store now runs `CREATE DATABASE IF NOT EXISTS` (server-level) before the schema, so a fresh
  server no longer fails with `1049 Unknown database`. Best-effort: a user without CREATE
  privilege gets a clear message to create it (or be granted the right); the DB name is validated
  to a safe identifier. `store.py` `build_server_url()` + `_ensure_database()`, called from
  `test_connection` and `ensure_schema`.
- **Report DB drivers install with the app.** `new-test-app` + `APP_SETUP.md` now run
  `pip install -e ".[dev,report-db]"`, so `PyMySQL` + `pyodbc` are present out of the box.
- **Skills also ship as project skills** (`.claude/skills/`) for the Claude Code interface/agent
  mode (where `/plugin` is unavailable); simplified `DEVELOPER_ONBOARDING.md`.

## v1.9.3 — 2026-08-31

Update-swap correctness, a windowed frozen launcher, and device-independent developer setup. MINOR.

- **`launcher.py` now ships inside `run.dist`** (`build_release.py` copies it into the swap unit),
  so a frozen station actually has its update supervisor — before this, `run.exe` alone had nothing
  to catch exit-42 and apply a staged update.
- **`RELEASE.json` rides inside `run.dist`** (the swap unit) and `core.app_version()` reads it there
  first; the launcher mirrors it to the deploy root after a swap. Fixes a bug where installing a new
  version left the station still reporting the old one (the version manifest wasn't part of the
  swapped artifact). Verified end-to-end: install 1.0.0→1.0.1 and rollback both change the reported
  version.
- **`run_station.py`** — a windowed entry for the frozen deploy (pywebview window + supervised
  backend + broker autostart), baked into the release at the deploy root by `build_release.py`.
- **The framework repo is now a Claude Code marketplace** (`.claude-plugin/marketplace.json` +
  `plugins/tmf-tools/`): the four dev skills (`new-test-app`, `add-bench-test`, `test-step-authoring`,
  `create-instrument-library`) install via `/plugin`, versioned with the framework, and are
  de-localized to `$FRAMEWORK_REMOTE` / `$TMF_INSTRUMENT_LIBRARY` so they run on any machine. New
  `docs/DEVELOPER_ONBOARDING.md` + `docs/templates/APP_SETUP.md`; two-remote (own-repo) app model.

## v1.9.2 — 2026-08-30

Frozen-layout: persistent state lives outside the swappable run.dist. PATCH.

- Live config + data (DB, relaunch marker, backups, last_known_good, debug captures) now
  resolve to an EXTERNAL deploy root via `TMF_STATE_DIR`, so an update swap of `run.dist`
  can never destroy or orphan them (UPDATES.md §1 frozen layout). `config.py`
  `resolve_state_dirs()` + a bundled-examples/external-live split; `launcher.py` passes
  `TMF_STATE_DIR` to the backend; `app.py` config + DB paths honor it. Source/tests are
  unchanged (no `TMF_STATE_DIR` = today's `backend/` layout).

## v1.9.1 — 2026-08-30

App-independent versioning. PATCH.

- An application now carries its OWN semver in the app-owned `app/<name>/VERSION` (starts
  1.0.0), independent of `core.__version__` (the framework version). `build_release.py
  --track app` uses it as the release version and records the framework version built upon
  as `pinned_fw_version`/`framework_version` in RELEASE.json.
- `core.app_version()` surfaces it at runtime (RELEASE.json when frozen, `app/*/VERSION` in
  source); `/branding` + `/update/offers` expose `app_version`; update applicability compares
  app-to-app (framework compatibility stays the `pinned_fw_version` check).
- release.yml template tag-guard now checks the app VERSION; new-test-app scaffolds VERSION.

## v1.9.0 — 2026-08-30

Remote debugging + updates + single-origin launcher. MINOR — new features, additive
contracts (no module `contract_version` bump).

- **Remote debugging** (`docs/REMOTE_DEBUG.md`): the Debug Server sidecar gains a rolling
  JSONL sink, a 30 s failure snapshot buffer, analog/digital logging discipline, an explicit
  `bind_host` + static token (rejects `0.0.0.0`), and live per-subsystem diag level control;
  the repo-root `tmf-debug` CLI (`pull`/`watch`/`digest`/`why`); Settings → Remote debugging
  toggle, supervised by `station.py`.
- **Updates** (`docs/UPDATES.md`): an un-brickable launcher (swap journal + startup
  reconciliation, backups + `last_known_good`, DB snapshot, 2-strike auto-recovery);
  notify-only `check` + idempotent `download`; `apply` refused mid-run (409); `rollback` +
  `status`; the AMC 402 gate; a hashed artifact zip in `build_release.py`; `release.yml` +
  `upstream-sync.yml` app templates.
- **Single-origin**: the backend serves the built SPA (`core/services/spa.py`); `station.py`
  one-click launcher (broker + backend + pywebview, graceful shutdown).
- **UI**: nav declutter (`UserMenu`), a waveform app logo + favicon, Settings
  Updates/Remote-debugging/License(AMC) cards.
- **Fixes**: the runs module subscribes `diag/#` (Diagnostics event tail now shows Python
  diag); core diagnostics gains `critical` + a per-subsystem level gate.
- **Keystation** (separate repo): a typed `amc` lease field (backward-compatible signing).

## v1.8.5 — 2026-08-11

Fix: the finish-reconcile fetched too early and missed the tail. PATCH.

- v1.8.4 fetched the persisted record once on `run-finished`, but the backend writes results
  asynchronously (the WS frame is broadcast before persistence), so the last group (e.g. VRA)
  wasn't written yet → the board/table came back short (e.g. 49 of 53, intermittently).
- `screens/Runs.tsx` now **polls the record until its `status` is terminal** — `run-finished`
  persists `status="finished"` under the same per-run lock, *after* every test-result (asyncio.Lock
  is FIFO), so `status=finished` ⇒ all results present. Guaranteed complete, no early stop.

## v1.8.4 — 2026-08-11

Runs: reconcile with the persisted record on finish. PATCH.

- On `run-finished`/`run-aborted`, `screens/Runs.tsx` re-loads the run's persisted results
  (authoritative + complete), closing the small gap where frames that arrive before the UI knows
  the new run's id would be filtered out. Live streaming still drives the board in real time; this
  guarantees the final table is 100% complete.

## v1.8.3 — 2026-08-11

Fix: Runs live view dropped test-results under load. MINOR (hook API additive).

- `useStream` gained an `onMessage(msg)` option that fires **synchronously for every frame**.
  The previous `last`-only API is lossy for accumulation: React batches state updates, so a burst
  of test-results (a whole run fires in milliseconds) collapsed into a few `[last]` effect runs and
  the live Runs board showed only a handful of the results — dials/table stayed mostly empty. The
  persisted record was always complete; only the live view lost frames.
- `screens/Runs.tsx` now accumulates results via `onMessage`, so the live table shows every
  measurement as it streams. `last`-based "latest value" consumers are unchanged.

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

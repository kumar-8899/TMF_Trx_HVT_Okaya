# Changelog

Framework releases. Semver (`docs/TEMPLATE.md` §versioning): **MAJOR** = a module
`contract_version` or locked-contract breaking change · **MINOR** = new modules /
features · **PATCH** = fixes. Every release is a git tag `v<version>`; the backend
stamps it into every record and diag event as `source_version`.

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

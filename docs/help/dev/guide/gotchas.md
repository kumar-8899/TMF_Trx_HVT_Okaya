# Gotchas & FAQ

Real mistakes, each one already made once. **When you hit a new one, add it here** (framework repo,
`docs/help/dev/guide/gotchas.md`) — this page is how the team's scar tissue becomes documentation.

## Setup & environment

- **`npm install` goes inside `frontend/`.** The only `package.json` is there; at the repo root it fails
  with `ENOENT`. Without it `station.py`'s auto-build fails with `'tsc' is not recognized`.
- **Several forks on one PC share one Python.** `pip install -e` points `core`, `instrumentlib` and
  `controller` at whichever fork installed *last* — so a test run can silently import another fork's code.
  Use a virtualenv per fork, or re-run the editable installs in the fork you're working on.
- **Git Bash mangles Windows flags** like `taskkill /PID 123` (it becomes a path). Use PowerShell for
  `taskkill`.
- **A stray process on `:8000` or `:1883` looks like your app.** Check what's listening before trusting a
  health check.
- **The station is `offline` and the log says `NotImplementedError` from `add_reader`.** The MQTT client needs
  a selector event loop, and newer uvicorn builds its own (Proactor on Windows), ignoring the loop policy.
  Start the backend through `run.py` / `station.py` (they use `core.serve`), never `uvicorn.run` or
  `python -m uvicorn` directly. A fresh virtualenv gets the newest uvicorn, so this only bites new installs.
- **Never stop processes by name** (`Stop-Process -Name python`). It kills every Python on the PC, including
  your other apps. Stop the one you started, by PID or by the port it listens on.
- **After Exit, a `python -m controller` is still running.** Before v1.27.4 a browser tab left open (a live
  WebSocket) stalled the graceful shutdown, and the watchdog's `os._exit` then orphaned the controller: still
  on MQTT, no instruments, so the next start had two controllers and runs flickered FAIL/PASS. Look for stray
  controllers by command line, stop the orphans by PID, and make any hard exit go through `core.serve.force_exit`.

## Forks & releases

- **Fork a release tag, never `main`.** And never push app commits to `upstream`: it is push-disabled on
  purpose.
- **Don't `git push --tags` from a fork.** You inherit every framework `v*` tag; app releases use the
  `app-v<version>` prefix and you push only that one tag.
- **Don't copy another app's repo and rename the remote.** You inherit its history, customer config and
  any drift. Use the `clone-test-app` skill.
- **Never hand-patch framework files in a fork** (e.g. `backend/build_release.py`). Two forks patched
  independently diverge from each other and from upstream. Fix it upstream, release, merge.

## Config & permissions

- **Permissions resolve at login/boot.** After adding a permission or changing roles: run
  `python -m tools.config_doctor --apply` **and log in again**.
- **Instrument instances have one source: Config → Instruments.** A `controller.json` `instruments` list is
  ignored under app supervision. Ids must match the `instance` names in your variable map.
- **Simulation is per instrument.** There is no global simulation switch under supervision.
- **Live `app.json` / `license.json` are gitignored.** Copy from the `*.example.json`; never commit secrets
  (the update token comes from the `TMF_UPDATE_TOKEN` environment variable).

## Instruments & the controller

- **One connection per instrument.** Under a supervised Python controller the controller holds the only
  live connection; the backend proxies through `instrument.call` / `instrument.status`. A second direct
  connection to a single-client (VISA `::SOCKET`, serial) instrument is refused or drifts.
- **Hardware ops must be `blocking=True`** when served by the controller, so they run on the worker pool
  instead of freezing the MQTT network thread (one hung instrument used to stall every other op).
- **A driver newer than the framework won't register.** A capability newer than your fork's `instrumentlib`
  (e.g. `safety_tester` needs v1.2.0+) is silently unregistered — fork a newer release.
- **The sequencer computes the verdict.** A crashed step used to report PASS with zero measurements; if you
  write a handler, raise or return measurements — never decide pass/fail yourself.

## Reports & export

- **A report export has a column-count ceiling.** The xlsx layout is `tests × selected fields` wide, and
  Excel stops at 16,384 columns (and the writer caps ~3 M cells because merged headers need openpyxl's
  in-memory mode). An app with thousands of tests should untick sub-columns or export TDMS. The API answers
  422 with the numbers rather than writing a broken file.
- **A test name repeated in one run keeps only its last result in the matrix** (`ReportStore._full` keys by
  `test_name`), in the Full view and in every export. Give repeated measurements distinct names.
- **nptdms cannot write an empty string channel** (no type can be inferred). `exporters/tdms.py` writes empty
  float channels for a zero-row export; don't "fix" it by passing an empty object array.

## MES

- **`mes` must not import `report` (or any module).** DB plumbing (URLs, engines, listings) lives in
  `core/services/dbconn.py`; both modules use it. Put new shared DB code there, not in a module.
- **Outbound MES has no outbox on purpose.** A failed push leaves only a status record (`mes_push`) and a loud
  UI prompt; Retry rebuilds the row from the run record. Don't add a queue or background retry — operators
  were explicit that a failed hand-off must be seen, not hidden.
- **The failure prompt is driven by persisted state, not a WebSocket frame.** `StreamHub` is latest-wins with
  no replay, so a one-shot frame can be missed; `MesAlertDialog` polls `GET /mes/alerts`.
- **Use `table()/column()`, not reflection, for customer tables.** Reflection needs catalog permissions the
  MES user often lacks, and typed-by-hand names must work. Never build SQL with f-strings from user input
  (the only DDL that does validates the identifier against `[A-Za-z0-9_]+` first).
- **A stored DB password is only reused for the same server.** `_same_server()` compares provider/host/port/user;
  keep that check when adding any "blank password = keep" path.
- **`latest_by` sorts as the database sorts the column.** Date + time in separate columns work as
  `[date, time]` only if both are real DATE/TIME types or ISO text; `dd/mm/yyyy` text sorts wrongly.
- **MySQL / SQL Server SQL isn't exercised in CI.** `SHOW DATABASES`, `sys.databases`, `ALTER TABLE … ADD`
  and ODBC timeouts are string-asserted only; verify on the real servers.

## Frontend

- **New pages go through `AppPage`, path must start with `/app/`.** Anything else is skipped with a console
  warning. Replace existing screens only via the five override keys.
- **Don't edit `frontend/src/screens/*`** in a fork — use overrides.

## Building & shipping

- **`cut-release.ps1` is the one build/release entry.** Don't call `build_release.py`,
  `build-installer.ps1` or `fetch-mosquitto.ps1` directly.
- **The frozen launcher is verified by opening a real window**, so the build needs an interactive desktop
  session (not a headless CI runner). A compile that boots the backend but can't open a window is a FAIL.
- **A clean client PC has no VC++ runtime** — the vendored Mosquitto needs `vcruntime140.dll` beside it (the
  build handles it; if `:1883` never opens on a new PC, check that first).
- **The Developer Hub is not in the build.** Customers get the user manual only; don't link a customer-facing
  page to developer docs.

- **`Path(__file__).parents[N]` is the source repo root - and one folder ABOVE the install in the frozen exe.** A
  map or config loaded that way silently came up empty. Use `core.paths.bundle_root()` (shipped, read-only payload:
  `app/<name>/`, `instrument_libs/`) and `state_root()` (config + data); report a failed load with
  `core.paths.load_failed(...)` so it is an `error`, not a warning nobody reads.
- **A driver works from source but crashes only in the installed exe** (NI-DAQmx *access violation*, "No package
  metadata was found for nitypes"). Two known causes: a bundled GUI toolkit's old `MSVCP140.dll` shadowing the real one
  (the backend exe excludes matplotlib/Qt/tkinter), and `importlib.metadata` dist-info that PyInstaller drops
  (derived from your drivers' imports). Add a `controller_probes` entry in `app/<slug>/release-probes.json` so the
  release gate makes a real driver call through the built exe - `docs/RELEASE_GATE.md`.
- **An app module is "Not Found" on a fresh install.** Licensing is fail-closed and the shipped license names only
  framework modules; entitle yours in `app/<slug>/license.entitlements.json` (the build now fails when you forget).

## Diagnosing a client PC

- **The Action/Error logs look empty.** Before v1.30.0 nothing recorded login, config or recipe changes and instrument
  failures were dropped below the persist threshold. Every `POST/PUT/PATCH/DELETE` is now audited centrally
  (`core/services/audit.py`); register an app's read-only POSTs with `audit.register_read_only_post(...)` instead of
  adding `record_action` calls.
- **"ni.write_digital failed" with no reason.** A timeout has an empty `str()`; errors now fall back to the class name and
  carry `cause` / `traceback_tail`. Have your driver log the traceback before wrapping.
- **The flight recorder does nothing on a client PC.** It runs there too since v1.30.0 (`run.exe --debug-server`,
  supervised by the launcher). For an air-gapped PC: `run.exe --debug-export out.zip` and carry the zip out.

## Process

- **Docs first.** Decide → update the doc → red test → code → green suites → CHANGELOG entry → tag.
- **Limits come from the product spec.** If a limit isn't in the spec, ask — don't invent one to get green.
- **Don't fake a passing state** with stubs; the bench is verified against real hardware and MQTT Explorer.

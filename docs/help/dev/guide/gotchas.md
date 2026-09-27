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

## Process

- **Docs first.** Decide → update the doc → red test → code → green suites → CHANGELOG entry → tag.
- **Limits come from the product spec.** If a limit isn't in the spec, ask — don't invent one to get green.
- **Don't fake a passing state** with stubs; the bench is verified against real hardware and MQTT Explorer.

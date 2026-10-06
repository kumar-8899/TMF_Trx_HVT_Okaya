---
name: new-test-app
description: Fork the Super_Test_App test-and-measurement framework into a new, self-contained test application. Use when the user wants to create/scaffold/bootstrap a NEW test bench or test application "on the framework", "from the framework", fork the framework for a customer/product line, start a new App_<Customer>, or turn a described end-of-line/safety/aging/endurance bench into a running app. This is the intelligent successor to tools/new_app.ps1 — it clones a release tag, wires remotes + app.json, copies the needed instrument drivers from the central Instrument_Library, scaffolds the app payload (variable map, recipe, controller step types), installs deps, and verifies in simulation. Do NOT use to add a single step type (use test-step-authoring) or a single driver (use create-instrument-library) to an EXISTING app.
---

# New Test Application (fork the framework)

Turn a described test bench into a **running, self-contained application** forked from the
Super_Test_App framework. Read `docs/TEMPLATE.md` §1–§1.2 in the framework before writing —
this skill implements that ownership contract; where they disagree, TEMPLATE.md wins.

Locations are **environment-driven** so this works on any machine (confirm with the user):
- Framework remote: **`$FRAMEWORK_REMOTE`** — a git URL, default
  `https://github.com/kumar-8899/Super_Test_App.git`. Fork from a **release tag** (e.g. `v1.2.1`),
  never a branch.
- Central drivers: **`$TMF_INSTRUMENT_LIBRARY`** — a local clone of the `Instrument_Library`
  repo (`instrument_libs/<capability>/<driver>.py`). If unset, ask the user for its path/URL.
- New app output + repo: a directory the user names, backed by the app's **own** git repo
  (each app is a separate repo — see Phase 2).

The golden rule (TEMPLATE.md §1): **only ever create/edit app-owned paths** —
`app/<name>/`, `instrument_libs/`, `backend/config/app.json`, `backend/modules/<app>_*/`,
`labview/App/`, `frontend/src/app/overrides/` (per-app Runs/Recipe/Maintenance screens,
§1.3, framework v1.4.0+). Never edit framework-owned files (`backend/core`,
`backend/instrumentlib`, `controller/`, the rest of `frontend/`, `docs/`, standard
modules). A framework change means: change the framework repo and cut a release, then
fork it.

---

## Phase 1 — Gather (do not scaffold until answered)

Ask, or read from a supplied spec (a bench/product spec document the user provides):

1. **Identity** — app/customer name, a slug (e.g. `acme_eol`), the app git remote (optional
   for a local-only fork), and which **framework release tag** to fork.
2. **Stations** — how many test sockets (1 = single-station UI).
3. **Controller** — `python` (auto-started, the usual for a new app) or `labview` (external).
   (Simulation vs hardware is decided later, per instrument, on the Instruments page.)
4. **Instruments** — each instrument model + role + connection. For each, decide: is there
   already a driver in central `Instrument_Library`? (list it) If not, it must be authored
   (Phase 3 uses the `create-instrument-library` skill).
5. **The test sequence** — the ordered tests, what each drives/reads, pass/fail logic, and the
   **limits (from the product spec — never invent them)**. Identify which tests are generic
   (drive a line, settle, read a signal, compare a window → core step types) vs product-specific
   (non-scalar instruments, custom judgement → an app step type).
6. **Signals/actions** — the named I/O lines and which instrument capability + args each maps to
   (this becomes the variable map). If the engineer has (or would rather fill in) a spreadsheet
   of the whole I/O system, use the **`system-blueprint`** skill to generate the variable map +
   instrument checklist from it — including later, as the full I/O is nailed down — instead of
   hand-authoring the map.

A missing answer produces an app that looks right and behaves wrong — stop and ask.

---

## Phase 2 — Fork the framework

```pwsh
# $FRAMEWORK_REMOTE defaults to https://github.com/kumar-8899/Super_Test_App.git
git clone --branch <TAG> $env:FRAMEWORK_REMOTE <app-dir>   # e.g. App_<Name>
cd <app-dir>
git remote rename origin upstream                # framework = upstream (READ-ONLY, for updates)
git remote set-url --push upstream DISABLE       # framework is read-only; never push to it
git remote add origin <app-remote>               # the app's OWN repo (create it first — see below)
git switch -c main && git push -u origin main
copy backend\config\app.example.json backend\config\app.json
copy backend\config\license.example.json backend\config\license.json
```

The `set-url --push upstream DISABLE` line is not optional: it makes any push to the framework
remote fail (bogus URL), so app commits can never land in the framework — even from a Git GUI, and
even if `origin` is somehow missing. A Git GUI derives a repo's identity from its remote, so a fork
whose only remote is the framework shows up **as** the framework and will offer to push your app's
commits straight to it.

**`origin` is required for a real app** — the app's own repo is where the team commits and releases:
- **With `gh`:** create + wire + push in one step —
  `gh repo create <org>/App_<Name> --private --source . --remote origin --push`
- **Without `gh`:** ask the user for the app repo URL, then `git remote add origin <url>` and push.
- **Local-only (no `origin`):** a deliberate fallback ONLY, and never silent — warn loudly (Phase 6)
  that the fork must be published to its own repo before it is opened in any Git GUI.

Edit `backend/config/app.json` (app-owned): `branding` (name/product/tagline/short),
`stations`, and `controller`:
```json
"controller": { "kind": "python", "config_file": "app/<name>/controller.json" }
```
(No `simulation` here — v1.5.1+: simulation is **per instrument**, the Simulated
toggle on the Instruments page.)

**Wire deployment + in-app updates (so the app is update-ready on day one):**
- In `app.json`, set the `updates` block: `github_repo` = the app's OWN repo (`<owner>/<repo>`, the
  `origin` you wired), `github_token` `""` (the client supplies a read token via the
  `TMF_UPDATE_TOKEN` env var — never commit it), `channel` `"stable"`, `allow_unverified` `true`
  (installs dev/unsigned releases as UNTRUSTED pre-Keystation; set `false` once Keystation signs),
  and `station_mode` — `"online"` (default; GitHub check/download) or `"air_gapped"` (USB
  install-file only). Set it explicitly per deployment; the app's own `app.release.json` should
  carry the value each client type actually uses.
- **Choose a release path** (both publish the same GitHub Release + four assets — the in-app
  updater and first-install docs don't care which):
  - **GitHub-hosted** — copy `docs/templates/release.yml` → `.github/workflows/release.yml`,
    set repo var `KS_PRODUCT_SLUG` = `<name>`. Fires on an **`app-v*`** tag: builds `--track app`
    (backend `run.exe` + frozen `run_station.exe` + vendored Mosquitto), signs a `.ksupdate`
    (dev-signed/untrusted without Keystation secrets), builds the offline `setup.exe`, publishes
    `<name>-<ver>.zip`, `.ksupdate`, `run_station.exe`, `<AppShort>-Setup-<ver>.exe`. Simple, but
    ~45 min / ~90 GitHub-Free minutes **per release** and its Nuitka cache never warms (see the
    note atop the template).
  - **Local (cost-conscious)** — run `deploy/cut-release.ps1` (inherited unchanged, no render — it
    auto-detects the sole app under `app/`, or takes `-Slug`). It is the ONE build/release entry:
    it invokes `fetch-mosquitto.ps1`, `build_release.py`, `sign_update.py` and `build-installer.ps1`
    internally, with a persistent local Nuitka cache; no CI minutes. Use `-BuildOnly` to build the
    artifacts without committing/tagging/publishing. **If you cut releases locally, also retarget
    the fork's `.github/workflows/release.yml` from `on: push: tags: ["app-v*"]` to
    `on: workflow_dispatch:`** so the local script's tag push doesn't also fire the hosted build.
  - Scaffold **both** regardless (harmless — the trigger in `release.yml` decides which is live).
- Scaffold `CONTRIBUTING.md.template` → `CONTRIBUTING.md` (fill `<App Name>` / `<slug>`): local
  release prerequisites + the app/framework ownership boundary in one onboarding page.
- Scaffold the **offline installer**: the fork inherits `deploy/installer.iss.template` +
  `deploy/build-installer.ps1` (render + compile the Inno setup.exe) and `deploy/vendor/mosquitto/`
  (the vendored broker; if absent run `deploy/fetch-mosquitto.ps1`). No edits needed — both are
  parameterized from `app.json` branding + `app/<name>/VERSION`.
- Cut a release by tagging `app-v<ver>` and pushing **only that tag**
  (`git tag app-v1.0.0 && git push origin app-v1.0.0`, or let `cut-release.ps1` do it) — NOT
  `git push --tags`. A fork inherits every framework `v*` tag, so the app's own version line
  collides with them and `--tags` would fire the workflow once per inherited tag; the `app-v`
  prefix scopes the trigger and keeps the lines apart. The prefix is tag-only — asset names + the
  updater's manifest version are unaffected.
- **First install** on a client is the offline `setup.exe` (double-click → maximized window; no
  Python, no pip, no broker service — the only post-install task is configuring instruments in-app). Every later
  version arrives via the in-app updater (online or from USB for air-gapped benches).
  `deploy/install-station.ps1` remains a scriptable/headless fallback. See `docs/DEPLOY_STATION.md`.

---

## Phase 3 — Instrument drivers (self-contained; copy from central)

For each instrument the app uses:
- **Driver exists in central** → copy `instrument_libs/<capability>/<driver>.py` (+ its
  `__init__.py`, and any custom transport under `transports/`) into the fork's own
  `instrument_libs/<capability>/`.
- **Driver missing** → author it with the **`create-instrument-library`** skill (into the
  central repo, conformance-gated), then copy it in.

Write `instrument_libs/__init__.py` importing only the categories you copied. The app must be
self-contained: `controller.json` `library_paths` points at the **fork root**, never at the
central repo. (See TEMPLATE.md §1.2; write `app/<name>/docs/INSTRUMENT_DRIVERS.md` recording
what was copied.)

A driver that declares a capability newer than the forked framework's `instrumentlib`
(e.g. `safety_tester` needs v1.2.0+) won't register — fork a newer framework release.

---

## Phase 4 — Scaffold the app payload (`app/<name>/`)

Create the app-owned tree (TEMPLATE.md §1.1):

- **`VERSION`** — the app's **own** version, independent of the framework (starts `1.0.0`).
  One line, e.g. `1.0.0`. `build_release.py --track app` reads it as the release version and
  records the framework version it was built upon as `pinned_fw_version` (two-tier, §4). The
  operator sees the app version; the framework number is provenance. Bump this per app change,
  not when the framework bumps.


- **`maps/<station>.json`** — the variable map. `signals`: each named line →
  `{instance, read|write, args, scale?, clamp?, units?}`; `actions`: non-scalar capabilities →
  `{instance, capability}`. One map per station, **same names** across identical stations.
  Tip for a shared analog input read into several windows: pass a **context** string as an
  extra read arg and have the sim driver key its value off it. If the I/O is captured in a
  System Blueprint spreadsheet, generate + maintain this file with the **`system-blueprint`**
  skill (`python -m tools.blueprint generate`) rather than editing it by hand.
- **`<name>_steps/`** — the controller step-type package. Author product-specific step types
  with the **`test-step-authoring`** skill (handler + schema + sim + tests; limits from
  `params`; `ctx.invoke` for non-scalar actions; the sequencer computes the verdict). Use the
  core 8 types (`set_output`, `measure_and_compare`, `wait`, `group`, `repeat`, `sweep`, `if`,
  `prompt_operator`) for the generic drive-settle-read-compare tests — no code.
- **`recipes/*.json`** — the sequence(s): controller-native steps (`{type,id,params}`, groups
  for each test) + limits from the spec. This is data.
- **`controller.json`** — `broker`, `library_paths:["<app repo root>"]` (the fork's own root —
  an absolute path or `"."` relative to where the controller runs; never the central library),
  `library_packages:["instrument_libs"]`, `stations:[{station,variable_map}]`,
  `step_type_packages:["<name>_steps"]`. **No `instruments` list and no global
  `simulation`** (v1.5.0/v1.5.1: instrument instances come from the app's Instruments
  page — configure them there, ids matching the variable map's `instance` names, each
  with its own Simulated toggle; a file list would be ignored). Document the required
  instances (id, library, params, sim) in `docs/INSTRUMENT_DRIVERS.md`.
- **`specs/<test>.md`** — one human-readable **test procedure spec** per test (procedure,
  delays, input params, output measurements, signals) + `specs/index.md`. Authoritative + the
  engineer edits these; `spec-lint` keeps code in sync. Template `docs/templates/test-spec.md`,
  format `docs/TEST_SPECS.md` (framework v1.8.0+). Also scaffold `tools/spec_lint.py`.
- **`tools/run_sim.py`** — an in-process runner (load libs + step package + map, drive the
  controller `Sequencer` over the recipe, print each measurement + verdict). Great fast proof.
  **Do not write it from scratch: copy `docs/templates/run_sim.py`** (it is in every fork) and
  edit only its two marked blocks, `INSTRUMENTS` (the instrument records: id = the map's
  `instance`, `simulated: True`) and `NEGATIVE_CASES` (a patched sim answer that must FAIL). The
  template already does the step that is easy to forget: the instruments must be **connected**
  (`loop.run(reg.connect_all())`) before the sequencer runs. Without it every read fails inside
  the step, no measurement prints, and it looks like a broken recipe. Sim answers are canned
  values (each driver's `_SIM` table), so a PASS needs spec limits that contain them.
- **`tests/test_sequence_sim.py`** — assert the sequence passes in sim + one negative case
  (import `run_recipe` and the `NEGATIVE_CASES` from `tools/run_sim.py`; do not duplicate the harness).
- **`docs/INSTRUMENT_DRIVERS.md`** — the driver copy record.

Recipe module (v1.3.0+, unified): recipes ARE controller-native — the recipe module
validates against the controller catalog (8 core types + the app's step-type
packages; wire `step_type_paths`/`step_type_packages` into the recipe module config)
and the Recipe UI authors/lists them; Runs starts them. Seed the recipe into the
store via the Recipes UI/API (create → publish) — files under `app/<name>/recipes/`
are the source data, the store is runtime.

Per-app UI (optional, v1.4.0+): custom Runs/Recipe/Maintenance screens go under
`frontend/src/app/overrides/` (default-export `{ key, component }`) — never edit
framework `screens/*`.

---

## Phase 5 — Install + verify

**The skill RUNS these installs itself, right after the fork exists — they are not
optional hand-off notes.** A fresh clone has no `node_modules` and no editable installs,
so the app cannot build, boot, or run `station.py` until they complete. Do them before any
verify/run step, and before telling the user the app is ready.

Backend deps + editable installs (run from `backend/`). The `desktop` extra pulls **pywebview** —
needed for the `python station.py` native window (else it falls back to the browser):
```pwsh
cd backend ; pip install -e instrumentlib ; pip install -e ".[dev,report-db,desktop]" ; cd ..
```

**Frontend deps — ALWAYS run `npm install` inside `frontend/`** (the only `package.json`
is there; running `npm` at the repo root fails `ENOENT: package.json`). Without it `tsc`/
`vite` don't exist, so `npm run build` — and `station.py`'s auto-build — fail with
`'tsc' is not recognized`:
```pwsh
cd frontend ; npm install ; cd ..
```

**One-click launcher (framework v1.9.0+):** `python station.py` serves the *built* SPA on
:8000, so it runs `npm run build` when `frontend/dist` is missing — which fails if the
`npm install` above hasn't run. After installing, either `python station.py` (it builds the
bundle once) or `python station.py --dev` (Vite + HMR, no prebuild). On a fork with no app
payload yet, the backend still boots and serves the UI; only the Python controller stays
down until `app/<name>/controller.json` exists (an expected warning, `/healthz` still green).

Verify (no broker, no hardware):
```pwsh
python app\<name>\tools\run_sim.py            # every parameter judged, VERDICT: PASS
python -m pytest app\<name>\tests -q
```

Optionally boot the stack (`.\dev.ps1`) and confirm the backend auto-starts the Python
controller (`/readyz` → station online; `/branding` → the app name). Then configure the
**instrument instances on Config → Instruments** (v1.5.0+: the page is the single source —
the controller gets NO instruments until then, even simulated; ids must match the variable
map) and restart. `run_sim.py` is in-process and needs no page config.

---

## Phase 6 — Hand off

Report: the fork path, what was copied/authored, `run_sim` verdict, and the remaining manual
items (configure the instrument instances on the Instruments page; author real limits if
placeholders were used; real-hardware transport swap). Commit the app payload on the fork's
`main`.

**If the fork was left without an `origin`** (local-only fallback), end the hand-off with a
blocking warning:

> ⚠️ **No `origin` set.** Before opening this in GitHub Desktop / any Git GUI, publish it to its
> own repo (`git remote add origin <url>` then push, or GitHub Desktop → **Publish repository**) —
> otherwise the GUI identifies it as the framework repo and offers to push your app's commits to it.
> (The framework remote is push-disabled, so such a push fails safe — but the fork should still own
> its `origin` before any GUI touches it.)

## Checklist

- [ ] Forked from a **release tag**; remotes wired: `upstream`=framework (push-disabled via
      `set-url --push … DISABLE`), `origin`=app repo (**required**, not optional)
- [ ] Only app-owned paths touched (TEMPLATE.md §1)
- [ ] Drivers **copied** into the fork's `instrument_libs/` — no runtime reference to central
- [ ] `instrument_libs/` (drivers) not confused with `backend/instrumentlib/` (base)
- [ ] App payload complete under `app/<name>/`; `app.json` `controller.config_file` wired
- [ ] No `instruments`/`simulation` in `controller.json` — instances live on the
      Instruments page (per-instrument Simulated), documented in INSTRUMENT_DRIVERS.md
- [ ] Limits come from the product spec, not invented
- [ ] A `specs/<test>.md` per test; `spec_lint.py` green (spec↔code in sync)
- [ ] Backend deps installed; **`npm install` run inside `frontend/`** (not repo root)
- [ ] `run_sim` PASS + a negative case fails; sim runs with no hardware

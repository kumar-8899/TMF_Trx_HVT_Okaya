# Deploying a station + shipping updates

How an app reaches a customer PC and how new versions get there. Framework-owned + generic — every
app fork inherits this unchanged (parameterized by the app's product slug + its GitHub repo).

There are **two separate layers**, and they never conflict:

| | Where | How |
|--|-------|-----|
| **First install** | a clean client PC | **`<AppShort>-Setup-<ver>.exe`** (offline; primary). Scripted fallback: `deploy/install-station.ps1` |
| **Every later version** | the same client PC | the in-app updater (Config → Updates), app-track only — online **or from USB** |

The dev PC (where you build the framework/app) uses `git merge` + `build_release.py` + a tag. A
client PC never builds — it only installs and updates.

---

## 1. First install (one time, per client PC) — the OFFLINE setup.exe

The frozen app is **self-contained**: `run_station.exe` bundles pywebview + the launcher, and the
vendored **Mosquitto** rides inside `run.dist`. So the installer needs **zero online setup** and the
**only** post-install task is configuring instruments in-app. Double-click the desktop shortcut → the
app opens **maximized** (title bar + close button; the close button shuts down cleanly, same as
the in-app "Exit station" button).

1. Copy `<AppShort>-Setup-<ver>.exe` (a GitHub Release asset — or from USB for an air-gapped site) to
   the client PC and run it.
2. The operator **picks the install dir** (default `C:\<Publisher>\<AppShort>` — a user-writable root,
   NOT Program Files, so the in-app updater can rename `run.dist`). The installer:
   - lays down `{app}\run.dist` (backend exe + UI + help + app definition + drivers + vendored broker)
     and `{app}\run_station.exe` beside it;
   - installs the **WebView2** runtime from the bundled offline standalone (a no-op when already
     present — it ships on Win11/current Win10);
   - grants `Users:Modify` on `{app}` (so a non-elevated operator can apply in-app updates);
   - creates a **Desktop + Start-Menu** shortcut → `run_station.exe` (maximized; pass
     `--fullscreen` yourself if a bench needs the old kiosk-style window instead).
3. Launch it. Then, once per bench: log in `admin`/`admin` (change it) and **configure the instrument
   instances on Config → Instruments** (IP/COM/port/simulated).

That instrument config lives in the external state (`{app}\config` + `{app}\data\tmf.sqlite`),
**outside `run.dist`**, so every future update preserves it — no re-setup.

**No Python, no pip, no Mosquitto service, no admin steps beyond the WebView2 install + the one-time
Modify grant.** WebView2 is the single OS-level dependency the installer carries.

### Building the setup.exe (dev side)
The app repo's `release.yml` builds it in CI (§2). To build locally, use the ONE build/release
entry — it runs `build_release.py --track app` and `build-installer.ps1` internally:
```powershell
deploy\cut-release.ps1 -BuildOnly         # run.dist + run_station.exe + setup.exe, no publish
                                          # (needs Inno Setup 6: winget install JRSoftware.InnoSetup)
```

**MSVC caveat — `run_station.exe` needs the tested C toolchain.** The build also
Nuitka-**onefile**-compiles the frozen windowed launcher (`run_station.exe`, the one `station.py`
entrypoint bundling pywebview + the `launcher` supervision module — no Python/pip on the client). On
a builder **without MSVC**, Nuitka falls back to its bundled zig/clang C backend, which has
historically produced a *standalone* dist that COMPILES but fails to boot for lean import graphs (the
same class of bug as the old `controller.exe "Failed to import encodings"` failure). Worse, a
compile can succeed yet produce an exe that boots the backend but can never open a **window** (a
Nuitka/pywebview plugin interaction). So `build_run_station_exe()` **actually runs** the compiled exe
**windowed** (no args, from a real station root) and asserts BOTH that it reaches `/healthz` AND that
a real window appears before calling it good — a compile that produces a windowless or non-booting
exe is caught, not shipped. (Windowed verification needs an interactive desktop session; build on a
desktop machine or the CI runner, not a headless box.)

This step is **fail-soft**: it never aborts the release. `run.dist` (the backend + the in-app update
artifact — `.zip` + `.ksupdate`) does **not** need `run_station.exe` at all; only the offline
first-install `setup.exe` does. So on a compile failure OR a failed runtime smoke test,
`build_release.py` prints a `WARNING`, removes the broken exe if any, and exits with a **distinct
code (3)** — `run.dist` + the update artifact are still produced. `deploy\build-installer.ps1` then
throws a clear "missing run_station.exe" error with the same guidance instead of silently building a
setup.exe around a broken launcher. `release.yml` (§2) checks that exit code and, on 3, **skips the
setup.exe steps and publishes the release without run_station.exe/setup.exe** rather than failing the
whole workflow (the in-app updater is unaffected).

If you hit this locally:
1. **Build where the tested toolchain is** — the release CI runner (`windows-latest`) ships MSVC
   Build Tools, so this is rare there; prefer building `run_station.exe`/`setup.exe` in CI over a
   bare MSVC-less dev box.
2. **Or install MSVC locally** — Visual Studio Build Tools, workload "Desktop development with
   C++" — then re-run `build_release.py --track app`; the default backend picks up `cl` automatically.
3. **Or skip the offline installer for now** — `run.dist` + the `.zip`/`.ksupdate` still ship; use
   `deploy\install-station.ps1` (below) for first-install until a rebuild fixes `run_station.exe`.

### Scripted / headless fallback — install-station.ps1
When you have no setup.exe (or want an unattended rollout), the older bootstrap still works, but it
needs a system **Python**, `pip install pywebview`, and a **Mosquitto** service:
```powershell
$env:TMF_UPDATE_TOKEN = "github_pat_..."   # read-only PAT for a private repo
deploy\install-station.ps1 -Product <slug> -Repo <owner>/<repo> [-Channel stable|beta] [-InstallDir <path>]
```
It is idempotent: ensures a **real** Python (it rejects the Microsoft Store `python.exe` alias stub
and installs a real interpreter), installs Mosquitto (:1883), `pip install pywebview`, then downloads
+ verifies + extracts the latest Release `<slug>-<ver>.zip` to `<InstallDir>\run.dist` and launches.

---

## 2. Cutting a release (dev side)

Two equivalent paths — they publish the **same** GitHub Release with the **same four assets**, so
nothing downstream (the in-app updater, first-install) cares which you use:

### 2a. Local — `deploy/cut-release.ps1` (cost-conscious, recommended on GitHub Free)

```powershell
# bump app/<slug>/VERSION + CHANGELOG.md first, then:
.\deploy\cut-release.ps1            # -Slug baked in by new-test-app; -DryRun / -SkipTests / -CacheDir
```
Runs every `release.yml` step on your machine with a **persistent** `NUITKA_CACHE_DIR`
(default `%LOCALAPPDATA%\tmf-nuitka-cache`; warm after the first build) — no CI minutes. It guards
that `VERSION` is **strictly newer** than the latest published `app-v*` tag, runs the tests, then
pushes the `app-v<ver>` tag **before** the build so a racing developer is rejected by git in
seconds, not after ~45 min. Prereqs (Python + `backend[dev,release]`, Node, Inno Setup 6, `gh`,
ideally MSVC Build Tools): `CONTRIBUTING.md`. If you use this, retarget the fork's own
`.github/workflows/release.yml` to `on: workflow_dispatch:` so the tag push doesn't also fire the
hosted build.

### 2b. GitHub-hosted — `release.yml` on the tag

1. Bump the app's `app/<slug>/VERSION` (independent semver) and update `CHANGELOG.md`.
2. Commit, then tag with the `app-v` prefix and push **only that tag**:
   ```bash
   git push origin main
   git tag app-v<ver> && git push origin app-v<ver>
   ```
   Use the `app-v` prefix (not plain `v<ver>`) — a fork inherits every framework `v*` tag, so the
   app's own version line collides with them, and `git push --tags` would push all the inherited
   framework tags and fire the workflow once per tag. Push the single `app-v<ver>` tag only
   (UPDATES.md §10.3).
3. The app repo's `.github/workflows/release.yml` (scaffolded by `new-test-app` from
   `docs/templates/release.yml`) runs on the `app-v*` tag: it guards tag==VERSION **and
   strictly-newer-than-latest**, tests, vendors Mosquitto, builds `build_release.py --track app
   --product <slug>` (backend `run.exe` + frozen `run_station.exe`), signs a `.ksupdate`, builds the
   offline `setup.exe`, and publishes the Release with **four assets**:
   - `<slug>-<ver>.zip` — the app (run.dist) the in-app updater verifies + swaps;
   - `<slug>-<ver>.ksupdate` — the signed trust envelope;
   - `run_station.exe` — the frozen windowed launcher (no Python on the client);
   - `<AppShort>-Setup-<ver>.exe` — the **offline first-install** installer.
   **Cost:** ~45 min ≈ 90 GitHub-Free minutes per release, and the Nuitka cache never warms across
   runs (cache is ref-scoped — see the note atop the template). Prefer 2a on a Free plan.

The `.zip` is a **complete** app: the UI, the in-app help, the app definition, the drivers, and the
vendored broker all ride inside `run.dist`, so an update refreshes everything (including your
**custom screen overrides**, compiled into the app's own `frontend/dist`). GitHub only runs a
workflow from the repo it lives in, so this file is per app (the skill scaffolds it).

---

## 3. Updating a client (the operator, in the app)

Config → **Updates**: **Check** (notify only — nothing downloads unasked) → **Download** (fetches +
verifies the artifact hash + stages it) → **Install** → **Relaunch**. The launcher swaps `run.dist`
journal-first (rename-only, so a power cut can't brick it), keeps a backup + a DB snapshot, and boots
the new version. If a new build fails to come up, it auto-reverts to the last-known-good; you can also
**Roll back** manually from the Updates page. Config + `tmf.sqlite` (instruments, users, recipes) are
untouched throughout.

### Air-gapped benches (no internet at the station)

Set **`updates.station_mode: "air_gapped"`** in that station's `app.json` (default is `"online"`).
It disables `/update/check` + `/update/download` (they'd just fail against GitHub anyway) and makes
**Install from file** the only in-app path — the Updates page hides the online half with an
explanation. A networked station keeps the default `"online"`, which conversely refuses
`install-file`. It's a **source** lock, independent of `allow_unverified` (trust). See UPDATES.md §9.

The online **Check/Download** talks to GitHub, so it can't run offline. Three ways to update
instead — all preserve config + data exactly like the online path:

1. **In-app, via the update-delivery tool (recommended, v1.26+).** `cut-release.ps1
   -BuildUpdatePackage` (or `deploy/build-update-package.ps1` directly) produces
   `<AppShort>-Update-<ver>.exe` — a small Inno-based tool, published as a 5th GitHub Release
   asset alongside the usual four, that carries an already-signed update (full and/or
   app-payload scope, see below) and does exactly one thing when run on the bench: copies those
   files into the station's **fixed** incoming-update slots
   (`{app}\data\updates\incoming\{full,app-payload}\update.{ksupdate,zip}`) and exits — no
   install, no registration, nothing else touched. Then in the app: Config → **Updates → Scan
   for updates on this PC**. That single click runs the **same** signature + hash verification
   and the same stage → Install → Relaunch (swap/rollback) pipeline as every other path here —
   this tool's only job is answering "where do the update files go," never verification or
   staging (deliberately: those stay in the one already-tested, already-signed pipeline —
   `core/services/updates.py`'s `UpdateService.scan_incoming`, `docs/UPDATES.md` §3.2/§4.1a).
2. **In-app, from USB, manual paths (fallback).** Copy the release's `<slug>-<ver>.ksupdate` +
   `<slug>-<ver>.zip` to the bench yourself (any location) and, on Config → **Updates**, use the
   "advanced" `.ksupdate path` / artifact `.zip path` fields under **Install from file**. Same
   pipeline as option 1 — this is what to reach for when the delivery tool wasn't built for this
   release, or the files came from somewhere other than a GitHub Release asset.
3. **Re-run setup.exe.** Running a newer `<AppShort>-Setup-<ver>.exe` (same Inno `AppId`) upgrades
   `{app}\run.dist` in place; `{app}\config` + `{app}\data` (DB, live config, instruments) are
   external and preserved. Use this for a full refresh or when the launcher itself changed (below).

**Patch-only updates (v1.26+, narrow compile surface — ADR
[0002](decisions/0002-nuitka-compile-scope.md)).** When a release changed only app-owned code (a
step-type bugfix, a new instrument driver, updated maps/specs — nothing in `core`/`modules`/
`controller`), cut it with `deploy/cut-release.ps1 -Scope app-payload` instead of the default
`-Scope full` — same version bump, same tag, same GitHub Release, just a `.zip` that is
`package_app_payload_artifact`'s smaller archive instead of the full `run.dist` — it skips the
compiled `run.exe`, the built frontend SPA, docs and the vendored broker. The manifest carries no
"scope" flag at all; the station detects which kind it received from the hash-verified content
itself (no `run.exe` at the top → app-payload) once staged, and the launcher swaps only
`run.dist/app` + `run.dist/instrument_libs`, leaving `run.exe` untouched. `build-update-package.ps1`
signs **both** scopes by default when there's app-owned payload to patch, so the ONE delivery
`.exe` for a release can carry either or both — the operator doesn't need to know which scope
applies; "Scan for updates on this PC" stages whichever slot(s) it finds. A single release still
only ever signs ONE scope for the plain GitHub-Release `.ksupdate`/`.zip` pair (§3's "exactly one"
rule, used by option 2 above) — the dual-scope bundling is specific to the delivery-tool path.

**Rollback is unaffected by any of the above.** However an update got onto the station — GitHub
Check/Download, the delivery tool, or manual paths — it lands as a staged offer through the exact
same `UpdateService` pipeline, and **Roll back to last known good** / **Roll back** (Config →
Updates, under "Installed builds") reverts to a **local backup already on the machine** — no file
delivery needed for a rollback, ever. The safety net is automatic too: two consecutive failed
boots after ANY update (full-scope or app-payload-scope) auto-revert to `last_known_good` and try
once more before stopping with a clear message (`UPDATES.md` §6). This holds for an app-payload
patch as much as a full update: `mark_last_known_good()` snapshots the WHOLE live `run.dist`,
including whatever app payload a prior patch already put there, so reverting the full tree
correctly undoes a bad patch too (`UPDATES.md` §4.1a).

> **Launcher-swap caveat.** The in-app updater swaps only `run.dist`. `run_station.exe` is a sibling
> in the station root, so an online/USB update does **not** refresh it. That's fine while the launcher
> is stable; a release that changes `run_station.exe` must be delivered by re-running **setup.exe** —
> such releases are flagged in the CHANGELOG.

---

## 4. Trust: dev/untrusted vs Keystation

The `.ksupdate` is a signed manifest. Pre-Keystation you don't have the signing ceremony, so:
- `release.yml` **dev-signs** the `.ksupdate` when no `KS_INTERMEDIATE_SEED`/`KS_INTERMEDIATE_CERT`
  secrets are set — the manifest exists and parses, but the stub provider flags it **verified: false
  (UNTRUSTED)**.
- A client installs an untrusted release **only** when its `app.json` has
  `updates.allow_unverified: true` (the example ships this on for internal use). The Updates page
  shows the offer as UNTRUSTED.
- When Keystation is stood up: put the real `KS_INTERMEDIATE_SEED`/`KS_INTERMEDIATE_CERT` in the app
  repo's Actions **secrets**, and set `updates.allow_unverified: false` on clients. The same pipeline
  then publishes **trusted** releases and clients install only verified manifests — no other change.

---

## 5. The read token (security)

A private app repo needs a read token for the client to poll releases:
- Scope it **narrowly** — a fine-grained PAT with **Contents: Read-only** on just that app repo.
- Supply it **per client** via the `TMF_UPDATE_TOKEN` environment variable (or the `-Token` arg to
  `install-station.ps1`). **Never** commit it — `app.json` `updates.github_token` stays `""`, and
  `app.release.json` (what the build ships) must not carry it.
- **Rotate** it on any staff change. A public app repo needs no token.

---

## See also
- `RUNNING.md` — running a station (dev + frozen).
- `SECURE_DISTRIBUTION.md` §5–6 — the build/sign/update pipeline + artifact layout.
- `APP_REPO.md` — the app-repo side of the two-tier model.
- `UPDATES.md` — the updater's guarantees (journal swap, rollback, auto-recovery).

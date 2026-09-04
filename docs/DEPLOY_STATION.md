# Deploying a station + shipping updates

How an app reaches a customer PC and how new versions get there. Framework-owned + generic — every
app fork inherits this unchanged (parameterized by the app's product slug + its GitHub repo).

There are **two separate layers**, and they never conflict:

| | Where | How |
|--|-------|-----|
| **First install** | a clean client PC | `deploy/install-station.ps1` (one time) |
| **Every later version** | the same client PC | the in-app updater (Config → Updates), app-track only |

The dev PC (where you build the framework/app) uses `git merge` + `build_release.py` + a `v*` tag.
A client PC never builds — it only installs and updates.

---

## 1. First install (one time, per client PC)

GitHub Releases delivers *updates*, not the first install — so there is a bootstrap script:

```powershell
deploy\install-station.ps1 -Product <slug> -Repo <owner>/<repo> `
    [-Token <read-pat>] [-Channel stable|beta] [-InstallDir <path>]
# e.g.
$env:TMF_UPDATE_TOKEN = "github_pat_..."   # read-only PAT for a private repo
deploy\install-station.ps1 -Product okaya_transformer -Repo kumar-8899/TMF_Trx_Functional_Oakay
```

It is idempotent and does the following:
1. Ensures a system **Python** (the launcher + `run_station.py` are not frozen — they need Python).
2. Installs the **Mosquitto** broker (service on :1883) if absent (`winget EclipseFoundation.Mosquitto`).
3. `pip install pywebview` for the native window (WebView2 is preinstalled on Win11).
4. Downloads the latest app-track Release's `<slug>-<ver>.zip`, **verifies its sha256** against the
   `.ksupdate` manifest's `full_artifact_hash`, extracts it to `<InstallDir>\run.dist`, and places
   `run_station.py` beside it.
5. Launches the station in a window.

Then, once per bench: log in `admin`/`admin` (change it) and **configure the instrument instances on
Config → Instruments** (IP/COM/port/simulated). That config lives in the external state
(`<InstallDir>\config` + `<InstallDir>\data\tmf.sqlite`), **outside `run.dist`**, so every future
update preserves it — no re-setup.

---

## 2. Cutting a release (dev side)

1. Bump the app's `app/<slug>/VERSION` (independent semver) and update `CHANGELOG.md`.
2. Commit, then tag and push:
   ```bash
   git tag v<ver> && git push origin main --tags
   ```
3. The app repo's `.github/workflows/release.yml` (scaffolded by `new-test-app` from
   `docs/templates/release.yml`) runs on the tag: it guards tag==VERSION, tests, builds
   `build_release.py --track app --product <slug>`, signs a `.ksupdate`, and publishes the Release
   with **three assets**: `<slug>-<ver>.zip` (the app — run.dist), `<slug>-<ver>.ksupdate` (trust
   envelope), and `run_station.py` (the launcher `install-station` places).

The `.zip` is a **complete** app: the UI, the in-app help, the app definition, and the drivers all
ride inside `run.dist`, so an update refreshes everything (including your **custom screen overrides**,
which are compiled into the app's own `frontend/dist`). GitHub only runs a workflow from the repo it
lives in, so this file is per app (the skill scaffolds it).

---

## 3. Updating a client (the operator, in the app)

Config → **Updates**: **Check** (notify only — nothing downloads unasked) → **Download** (fetches +
verifies the artifact hash + stages it) → **Install** → **Relaunch**. The launcher swaps `run.dist`
journal-first (rename-only, so a power cut can't brick it), keeps a backup + a DB snapshot, and boots
the new version. If a new build fails to come up, it auto-reverts to the last-known-good; you can also
**Roll back** manually from the Updates page. Config + `tmf.sqlite` (instruments, users, recipes) are
untouched throughout.

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

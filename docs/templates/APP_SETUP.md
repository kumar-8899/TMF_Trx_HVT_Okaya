# APP_SETUP — <App Name>

Per-app checklist. `new-test-app` copies this into the app repo root and fills `<App Name>` /
`<slug>`. Work top to bottom. Steps marked **(deferred)** wait for the Keystation/signing phase —
skip them while running in dev mode.

## 1. Remotes (two-remote model)

```pwsh
git remote -v
# expect:
#   origin          <this app's own repo>            (where you commit + release)     [push OK]
#   upstream (fetch) https://github.com/kumar-8899/Super_Test_App.git  (framework; fetch tags)
#   upstream (push)  DISABLE                          (read-only; app commits never go here)
```
Make it so:
```pwsh
git remote set-url upstream https://github.com/kumar-8899/Super_Test_App.git  # if it's a local path
git remote set-url --push upstream DISABLE                                     # framework read-only
git remote add origin <app-repo-url>                                           # REQUIRED
```
`origin` is **required**, not optional. A Git GUI derives a repo's identity from its remote — a fork
whose only remote is the framework shows up **as** the framework and offers to push your app's
commits to it. Disabling push to `upstream` makes that fail safe; owning an `origin` before you open
the fork in any GUI removes the trap. (`gh` one-liner:
`gh repo create <org-or-user>/App_<Name> --private --source . --remote origin --push`.)

## 2. Config (dev mode)

```pwsh
copy backend\config\app.example.json backend\config\app.json     # if not already present
copy backend\config\license.example.json backend\config\license.json
```
- `branding` → the customer/product name.
- `stations` → number of sockets.
- `controller` → `{ "kind": "python", "config_file": "app/<slug>/controller.json" }` (or `labview`).
- Licensing stays the **stub** (dev) — no `licensing` block needed yet.

## 3. Install + verify (no hardware)

```pwsh
cd backend ; pip install -e instrumentlib ; pip install -e ".[dev,report-db]" ; cd ..
cd frontend ; npm install ; cd ..
python app\<slug>\tools\run_sim.py        # every parameter judged, VERDICT: PASS
python -m pytest app\<slug>\tests -q
```

## 4. Run

```pwsh
python station.py            # native window (or --dev for Vite/HMR)
```
Login `admin` / `admin`. Configure instrument instances on **Config → Instruments** (ids match the
variable map), then restart.

## 5. Keep up with the framework

```pwsh
git fetch upstream --tags
git merge vX.Y.Z             # clean iff only app-owned paths were edited (TEMPLATE.md §1)
python -m tools.config_doctor --apply
```

## 6. Licensing + signed releases — **(deferred)**

When the Keystation/signing phase is enabled:
- Register the product slug (`licensing.product`) with the issuer and set `licensing.provider: keystation`.
- Add `updates.github_repo` = this app repo; set CI secrets (signing seed/cert).
- `.github/workflows/release.yml` builds → signs the `.ksupdate` → publishes the Release; stations
  then update via **Settings → Updates** (Check → Download → Install → Relaunch). See `docs/UPDATES.md`.

Until then: releases are dev builds (`build_release.py`), distributed manually; the git-merge path
(step 5) is how apps track the framework.

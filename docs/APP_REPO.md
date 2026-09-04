# Building a customer application repo

> **Current phase (personal-GitHub, licensing deferred).** The recommended way to scaffold an app
> is the **`new-test-app`** skill (install the `tmf-tools` plugin — see `docs/DEVELOPER_ONBOARDING.md`),
> not the legacy `tools/new_app.*` generator. Framework remote = `$FRAMEWORK_REMOTE`
> (`https://github.com/kumar-8899/Super_Test_App.git`). Apps run in **dev mode** (stub licensing) and
> track the framework via **git merge** (below). The signing / Keystation / `release.yml` steps in
> this doc are the **eventual** pipeline — deferred until the licensing phase. Org move later = a
> remote-URL change only.

The two-tier model (TEMPLATE.md): **you** maintain one framework (this repo, source +
tags); **Exeliq devs** build customer applications, each a **separate repo forked from a
framework tag** and licensed per customer. This is the app-repo side.

```
framework (source + git tags)  ──fork a tag──►  App_<Customer> (editable fork)
                                                    └── its own CI: Nuitka → sign → Release (LICENSED build)
```

## Scaffold a new app

**Interactive (recommended)** — from the framework repo, run and answer the prompts
(framework tag, customer, product slug, app repo, output dir). It clones the framework
at the tag, wires remotes (framework = `upstream`, **push-disabled** via
`git remote set-url --push upstream DISABLE`; app = `origin`, **required**), and generates the
app-owned files:

> **Why `origin` is required + `upstream` push-disabled:** a Git GUI derives a repo's identity from
> its remote. A fork whose only remote is the framework appears **as** the framework and offers to
> push the app's commits straight to it. Disabling push to `upstream` makes that fail safe; owning an
> `origin` before the fork is opened in any GUI removes the trap entirely.

```
tools\new_app.bat            (or: powershell -ExecutionPolicy Bypass -File tools\new_app.ps1)
```

**Manual** — clone the tag yourself, then run the generator:
```bash
git clone <framework-remote> App_Acme_EOL && cd App_Acme_EOL && git checkout v1.1.0
python tools/new_app.py --slug exeliq.acme_eol --customer "Acme EOL" \
    --framework-tag v1.1.0 --app-repo exeliq/app-acme-eol --out .
```

It writes **only app-owned paths** (TEMPLATE.md §1), **enables every framework module**
present in the fork (discovered on disk — future modules included automatically) plus the
app module, and never pushes:

| generated | what |
|---|---|
| `backend/config/app.json` | product identity (`licensing.product` = the slug), branding, `updates.github_repo` = the app repo, and the app module enabled |
| `backend/modules/<mod>/` | a prefixed, collision-proof app module stub (`GET /<mod>/info`) — where customer features go |
| `.github/workflows/release.yml` | the **app-track** CI: build → sign the app `.ksupdate` → publish the app's GitHub Release |
| `APP_SETUP.md` | the per-app checklist (remotes → secrets → register product → first release) |

Then follow the generated `APP_SETUP.md`.

## What the app owns vs inherits
- **Owns** (edits): the four paths above + branding + recipes/users/instruments (config).
- **Inherits** (read-only): all framework code, plus the build/sign **tools**
  (`backend/build_release.py`, `tools/ks_release_signer/`) it runs in its own CI.

## Licensing
The app is the **licensed unit** (app track). Its lease is issued against
`licensing.product` (the slug), pins the framework version, and grants the customer's
entitlements. The framework itself is issuer-global and not customer-licensed. Enforcement
is identical (the framework gate reads `plugin.<module>` from the lease).

## Upgrading to a newer framework
```bash
git fetch upstream --tags && git merge vX.Y.Z    # clean iff only app-owned paths were edited
# re-pin: the app's next release build stamps --pinned-fw-version X.Y.Z
```

See RELEASE_HOWTO.md (framework tags) and SECURE_DISTRIBUTION.md (§5–6, the pipeline).

## Releases & updates (UPDATES.md)

An app repo ships two workflows the framework does not (framework repo = `ci.yml` only):

- **`.github/workflows/release.yml`** (from `docs/templates/release.yml`) — on an **`app-v*`**
  tag: tag-matches-version guard → tests → `build_release.py` (Nuitka + a hashed artifact `.zip` +
  `full_artifact_hash` in `RELEASE.json`) → sign the `.ksupdate` → publish a Release with the
  CHANGELOG section as the body and its assets: `<slug>-<version>.ksupdate` (trust) +
  `<slug>-<version>.zip` (the run.dist the station verifies and swaps) + `run_station.py`.
  Tag `app-v<version>` and push **only that tag** (never `git push --tags` — a fork inherits
  every framework `v*` tag; the `app-v` prefix keeps the app's version line from colliding with
  them and scopes the trigger). The prefix is a tag convention only — asset names + the updater's
  manifest version are unaffected (UPDATES.md §10.3).
- **`.github/workflows/upstream-sync.yml`** (from `docs/templates/upstream-sync.yml`) — weekly
  same-MAJOR framework merge → PR, never auto-merged (drift detection).

The station side (Settings → Updates) is notify-only: **Check → Download → Install → Relaunch**,
with rollback to last-known-good and a bounded auto-recovery in the launcher. See UPDATES.md.

**Client deployment + the end-to-end update flow** (first install via `deploy/install-station.ps1`;
the `updates` config block; cutting a release; the read-token security note; dev-untrusted vs
Keystation trust) is [DEPLOY_STATION.md](DEPLOY_STATION.md). `new-test-app` scaffolds `release.yml`
and the `updates` block into each fork, so an app is deploy- + update-ready on day one.

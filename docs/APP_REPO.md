# Building a customer application repo

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
at the tag, wires remotes (framework = `upstream`, app = `origin`), and generates the
app-owned files:
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

- **`.github/workflows/release.yml`** (from `docs/templates/release.yml`) — on a `v*` tag:
  tag-matches-version guard → tests → `build_release.py` (Nuitka + a hashed artifact `.zip` +
  `full_artifact_hash` in `RELEASE.json`) → sign the `.ksupdate` → publish a Release with the
  CHANGELOG section as the body and **two assets**: `<slug>-<version>.ksupdate` (trust) +
  `<slug>-<version>.zip` (the run.dist the station verifies and swaps).
- **`.github/workflows/upstream-sync.yml`** (from `docs/templates/upstream-sync.yml`) — weekly
  same-MAJOR framework merge → PR, never auto-merged (drift detection).

The station side (Settings → Updates) is notify-only: **Check → Download → Install → Relaunch**,
with rollback to last-known-good and a bounded auto-recovery in the launcher. See UPDATES.md.

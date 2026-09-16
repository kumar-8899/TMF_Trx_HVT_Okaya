---
name: clone-test-app
description: Start a new test application by cloning an EXISTING forked app (on the Super_Test_App framework) that is similar to what's needed, instead of starting from a bare framework tag. Use when the user wants to "clone", "copy", "base on", "reuse", or "start from" an existing app/bench for a new customer/product/station — a new bench is similar enough to one already built (same or overlapping instruments, test sequence, or UI) that re-authoring the app payload from scratch would just be re-typing the old one. It re-homes remotes to a FRESH framework fork (never the source app) so the new app keeps a clean upstream-tracking history and never inherits the source app's git history, customer-specific config, or secrets, then overlays and renames the source app's payload (app/<slug>/, instrument_libs/, backend/modules/<slug>_*, frontend overrides) onto it. Do NOT use for a brand-new bench with nothing comparable already built (use new-test-app) or to add one test to an app that already exists (use add-bench-test).
---

# Clone an existing app (fork the framework, reuse a similar app's payload)

Start a **new, independent** application from an **existing forked app** that is close to
what's needed — same or overlapping instruments, a similar test sequence, similar UI — instead
of authoring the app payload from an interview (that's `new-test-app`). The new app is a
**separate product with its own repo, its own version line, and its own git history**; the
source app is a *content donor*, never a git remote the new app depends on.

Read `docs/TEMPLATE.md` §1–§1.3 first — this skill still produces a TEMPLATE.md-compliant
fork; where they disagree, TEMPLATE.md wins. If nothing comparable already exists, stop and
use **`new-test-app`** instead — this skill only saves work when there's a real starting point.

## Why not just `git clone` the source app directly

Cloning the source app's repo verbatim and renaming remotes seems simpler, but breaks three
things this skill exists to avoid:

1. **History leakage.** An app repo's commit history routinely carries customer-specific detail
   (limits, site names, personal names, sometimes secrets) in messages and old file states —
   fine for *that* customer's repo, not something to hand to a *different* customer's repo.
2. **Wrong `upstream`.** TEMPLATE.md's whole upgrade model (§3, `git fetch upstream --tags &&
   git merge v<X>`) assumes `upstream` is the **framework**. If the new app's `upstream` ends up
   being the source app instead, a later framework release can't be merged in cleanly.
3. **Inherited drift.** If the source app ever accumulated an edit to a framework-owned file
   (a violation of §1, but it happens), cloning it verbatim ships that drift into a second app.
   Forking fresh from a framework tag and only overlaying **app-owned** paths (§1's table)
   guarantees the new app starts clean even if the source app didn't.

So: fork the **framework** at a tag (exactly like `new-test-app` Phase 2) to get clean history
and a correct `upstream`, then copy across only the source app's app-owned content, renamed.

---

## Phase 1 — Gather (do not scaffold until answered)

1. **Source app** — a local path or git URL to the existing app repo to clone from, and which
   ref (a specific `app-v*` tag = a known-good release, or `main` = latest in-progress work;
   default: latest `app-v*` tag if one exists, else `main`).
2. **New identity** — new customer/app name, its slug (`app/<slug>/`, `<slug>_steps`,
   `backend/modules/<slug>_*`), the new app's **own** git remote (or an explicit local-only
   fallback — same Phase 6 warning as `new-test-app`).
3. **Framework base** — fork the framework at:
   - the **exact tag the source app is currently pinned to** (read its
     `backend/core/__init__.py` `__version__` — guarantees the copied payload is dropped onto
     the identical framework contract it was built and tested against), or
   - the **latest framework release** (recommended if the jump isn't large — picks up fixes,
     at the cost of re-verifying the copied payload against anything that changed).
   Default to the source app's exact pin unless the user wants latest.
4. **What's actually reused vs new** — walk what's being kept as-is vs needs work for the new
   customer:
   - Instruments: identical bench, or some swapped/added/removed?
   - Test sequence + **limits**: identical tests are rare across customers even on the same
     bench — assume the **limits need a new product spec** unless the user explicitly confirms
     they're unchanged. Never silently carry old limits into a new customer's app (the same
     "limits from the spec, never invented" rule from `add-bench-test` applies here).
   - Stations count, controller kind (python/labview), per-app UI overrides.
5. **Confirm no live config is carried over** — the source app's real `backend/config/app.json`
   / `license.json` (branding, possibly a real license key or update-repo token) is **never**
   copied verbatim; only its *shape* (which knobs it set) is used as a reference when filling in
   the new app's own `app.example.json`/`license.example.json`.

A missing answer here produces an app that looks like the old one and quietly runs its old
numbers — stop and ask, same discipline as `new-test-app` Phase 1.

---

## Phase 2 — Fork the framework (clean history, correct `upstream`)

Identical to `new-test-app` Phase 2 — this is what gives the new app a mergeable relationship
with future framework releases:

```pwsh
# $FRAMEWORK_REMOTE defaults to https://github.com/kumar-8899/Super_Test_App.git
git clone --branch <TAG> $env:FRAMEWORK_REMOTE <new-app-dir>
cd <new-app-dir>
git remote rename origin upstream                # framework = upstream (READ-ONLY)
git remote set-url --push upstream DISABLE       # never push to the framework
git remote add origin <new-app-remote>           # the NEW app's OWN repo
git switch -c main && git push -u origin main
copy backend\config\app.example.json backend\config\app.json
copy backend\config\license.example.json backend\config\license.json
```

`<TAG>` is whichever framework version Phase 1 settled on. The source app's repo is **not** a
remote on the new app at any point — it is only ever read from (Phase 3), never fetched into or
merged with the new app's history.

---

## Phase 3 — Overlay the source app's payload (copy + rename, never the source's history)

Get a read-only checkout of the source app at the chosen ref (`git clone --branch/--depth 1
<source-app-url-or-path> <tmp-dir>`, or just read it in place if it's already a local
checkout) — this is a **scratch copy**, discard it once Phase 3 is done, and never add it as a
git remote of `<new-app-dir>`.

Copy **only the app-owned paths** (TEMPLATE.md §1's table) from the scratch copy into
`<new-app-dir>`, then rename the old slug to the new one throughout what was just copied:

| Copy from source app | Into new app | Rename inside |
|---|---|---|
| `app/<old-slug>/` | `app/<new-slug>/` | `<old-slug>_steps` → `<new-slug>_steps` (dir + package name), `controller.json` `step_type_packages`/`library_paths`, `tools/run_sim.py` imports, `specs/index.md` |
| `instrument_libs/` | `instrument_libs/` | nothing (driver code is instrument-specific, not app-specific) |
| `backend/modules/<old-app>_*/` (if any) | `backend/modules/<new-app>_*/` | dir name, `manifest.json` `name`, any internal package imports |
| `frontend/src/app/overrides/*.tsx` + subfolders | same, subfolder renamed | the subfolder holding supporting components (e.g. `overrides/<old-slug>/` → `overrides/<new-slug>/`) and the `.tsx` files' imports of it |
| `labview/App/` (only if `controller.kind == "labview"`) | `labview/App/` | project-specific names per the LabVIEW project, done inside the IDE (TEMPLATE.md §5 — never move `.vi` files with the filesystem) |

**Never copy:** the source app's actual `backend/config/app.json`/`license.json` (Phase 1 item
5), `backend/config/known_issues/`, `backend/data/` (gitignored, runtime-only anyway), `.env`,
or **any** git history/metadata from the source checkout.

After copying, grep the new app's `app/<new-slug>/` and `backend/modules/<new-app>_*/` trees for
the **old** slug/app name (`grep -ri "<old-slug>"`) — anything left is a missed rename (a stale
import path, a docstring, a step-type registry key) and will break at runtime or silently
misregister.

Set `app/<new-slug>/VERSION` to `1.0.0` (a new product line gets its own version history) unless
Phase 1 explicitly decided this is a continuation of the same product for the same customer.

---

## Phase 4 — Re-key identity + config

Same knobs `new-test-app` Phase 2 wires, now filled from the NEW customer's answers, not
inherited from the source:

- `backend/config/app.json` — **new** `branding` (name/product/tagline/short — never the old
  app's), `stations`, `controller.config_file: "app/<new-slug>/controller.json"`.
- `updates` block — `github_repo` = the **new** app's own repo (not the source app's), fresh
  `channel`/`allow_unverified`/`station_mode` per Phase 1 of `new-test-app`'s guidance.
- Deploy naming: `.github/workflows/release.yml` `KS_PRODUCT_SLUG` = `<new-slug>`; the Inno
  installer (`deploy/installer.iss.template` render) needs its **own distinct product GUID** —
  reusing the source app's would make Windows treat the two apps as the same installed product
  (one install silently overwrites/uninstalls the other).
- `CONTRIBUTING.md.template` → `CONTRIBUTING.md`, rendered with the new name/slug.

---

## Phase 5 — Reconcile what was reused (don't ship inherited numbers as if new)

For each test carried over from the source app, resolve it explicitly — this is the step a
straight `git clone` of the source app would let slide silently:

- **Identical** (same bench, same customer requirement) → keep as-is.
- **Same test, different limits** → update `recipes/*.json` limits and `specs/<test>.md` from
  the NEW product spec; re-run `spec_lint.py`.
- **Doesn't apply to the new bench** → remove the recipe step/group; leave the step type in
  place only if another kept test still uses it, otherwise delete it too.
- **New test the source app didn't have** → build it with `add-bench-test`, in dependency order.

---

## Phase 6 — Install + verify (identical gate to `new-test-app` Phase 5)

```pwsh
cd backend ; pip install -e instrumentlib ; pip install -e ".[dev,report-db,desktop]" ; cd ..
cd frontend ; npm install ; cd ..
python app\<new-slug>\tools\run_sim.py            # every parameter judged, VERDICT: PASS
python -m pytest app\<new-slug>\tests -q
python app\<new-slug>\tools\spec_lint.py          # spec <-> code in sync
```

Boot `.\dev.ps1`, confirm `/readyz` reports the station online and `/branding` shows the **new**
app's name (not the source app's), then configure instrument instances on Config → Instruments
(ids must match the variable map — copied from the source app, so likely already right if the
bench is genuinely similar) and restart.

---

## Phase 7 — Hand off

Report: which app was cloned from (repo + ref), the framework tag forked, what was renamed,
which tests/limits were kept vs changed vs added (Phase 5), `run_sim`/`spec_lint` results, and
remaining manual items. Commit the payload on the new fork's `main`; if it was left without an
`origin`, give the same blocking warning `new-test-app` Phase 6 gives.

## Checklist

- [ ] New app's history is rooted at a **framework tag clone** — no source app history/commit
      messages carried over
- [ ] Remotes: `upstream` = **framework** (push-disabled), `origin` = the **new** app's own repo
      — the source app is not a remote anywhere on the new fork
- [ ] No live `app.json`/`license.json`/secrets copied from the source app
- [ ] Old slug fully renamed everywhere copied — `grep -ri "<old-slug>"` in the new payload
      comes back empty
- [ ] Branding is the new customer's, not inherited
- [ ] Every kept test's limits explicitly reconciled against the NEW product spec (Phase 5) —
      none silently carried over unconfirmed
- [ ] Fresh installer product GUID (won't collide with the source app's installed product)
- [ ] `run_sim` PASS, `pytest` green, `spec_lint.py` clean after the copy + rename
- [ ] Only app-owned paths touched (TEMPLATE.md §1)

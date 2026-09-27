# Ownership boundary

> **An application only creates or edits app-owned paths. Framework-owned files are read-only downstream.**
> If an app needs a framework change, change it in the framework repo and release — never patch it in the
> fork. This one rule is what keeps `git merge` clean for the life of the app.

```tmf:diagram
boundary
```

## Try it

```tmf:ownership
```

## The lists

**App-owned (yours; upstream merges never touch these)**

| Path | What |
|---|---|
| `app/<name>/` | the app payload: step-type package, variable maps, recipes, specs, `controller.json`, tools, tests |
| `instrument_libs/` | drivers this app copied from the central Instrument_Library |
| `backend/modules/<app>_*/` | app-specific backend modules — **prefix with the app name** so a future framework module can never collide |
| `frontend/src/app/overrides/` | per-app screens **and new pages** (`AppPage`, path must start with `/app/`) |
| `labview/App/` | application LabVIEW |
| `backend/config/app.json`, `license.json` | live station config + license (gitignored; the framework ships `*.example.json`) |

**Framework-owned (read-only in a fork):** `backend/core`, `backend/instrumentlib`, the standard modules,
`controller/`, the rest of `frontend/`, `docs/`, `deploy/`, `tools/`, `station.py`, `dev.ps1`.

## "I need to change a framework file"

1. Don't. Open the **framework** repo, make the change on a branch (doc → test → code → suites →
   CHANGELOG), cut a release.
2. In your fork: `git fetch upstream --tags && git merge vX.Y.Z`.
3. If it's urgent, a *temporary* local patch is a debt: it will conflict on the next merge — record it and
   remove it when the release lands.

## Extension points that keep you inside the boundary

| You want to… | Use |
|---|---|
| Replace Runs / Recipes / Maintenance UI | a screen override in `frontend/src/app/overrides/` |
| Add a whole new page + nav entry | `export const pages: AppPage[]` from an override file |
| Add product-specific test logic | a step-type package under `app/<name>/` (`test-step-authoring` skill) |
| Add app-specific server behaviour | a `backend/modules/<app>_*/` module |
| Document your own bench for operators | `app/<name>/portal/*.md` (+ `img/`, bundled PDFs in `library/`) — appears in the User Portal under **This app** |

Deeper: [Application template](help:dev-template) · [Building an app repo](help:dev-app-repo) ·
[Extension how-tos](help:dev-extending).

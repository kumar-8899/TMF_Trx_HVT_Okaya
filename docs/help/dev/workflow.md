# Dev workflow

## Run
```pwsh
.\dev.ps1                 # broker + backend (:8000) + frontend (:5173)
cd backend; python run.py
cd frontend; npm run dev
.\debug.ps1 -NoAuth       # Debug Server sidecar (:8001)
```

## Test
```pwsh
cd backend;  python -m pytest -q
cd frontend; npx tsc --noEmit; npx vitest run; npm run build
```
Backend testers live next to each module (`modules/*/tester`, `debug_server/tester`); add to `pyproject.toml` `testpaths` if a new top-level package.

## Config & license
`backend/config/app.json` + `license.json` are **gitignored live files** (edit on disk; the `*.example.json` are committed). When you add a module/permission, update **both** examples and the live files, then restart the backend and re-login (permissions + roles resolve at login).

## Conventions
- One role per user; modules consume **permissions, never roles**.
- Append-first records with the RAG envelope; loud, structured failures.
- No stub code — modules are exercised against real LabVIEW + MQTT.
- Commit messages end with the Co-Authored-By footer; small commits.
- Windows console is cp1252 — keep `print()` ASCII (no `→`, `✓`).

## Docs
User docs: `docs/help/user/`. Dev guides: `docs/help/dev/`. Design contracts: `docs/` + `docs/contracts/`. The help module serves all of these; **keep them current as features change** (see the help catalog in `modules/help/catalog.py`).

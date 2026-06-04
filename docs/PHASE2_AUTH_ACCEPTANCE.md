# Phase 2 — Auth acceptance

First business module (build order step 2). Permission-first, headless; the React
UI is a later phase. Requirement set:
[User_Authentication_Module_Summary.md](User_Authentication_Module_Summary.md);
contract: [contracts/auth.md](contracts/auth.md).

## Status (backend)

| Criterion | Proven by | Status |
|---|---|---|
| Permission-first port (`require_permission`, wildcard) | `tests/test_security.py` | ✅ |
| Login resolves permissions at login + fills `core.auth` | `modules/auth/tester` | ✅ |
| Wrong/unknown credentials rejected | `modules/auth/tester` | ✅ |
| Opaque session: logout revoke, TTL/expiry | `modules/auth/tester` | ✅ |
| Single active session (re-login revokes prior) | tester + `tests/test_auth_e2e.py` | ✅ |
| User state machine (LOCKED/RESET/INACTIVE) | `modules/auth/tester` | ✅ |
| Password policy + change-password clears RESET | `modules/auth/tester` | ✅ |
| User management, gated on `AUTH.MANAGE_USERS`, audited | `modules/auth/tester` | ✅ |
| Authenticator seam (password + no_auth by config) | `modules/auth/tester` | ✅ |
| Full app: login → `/auth/me` → gate 401/403/200 | `tests/test_auth_e2e.py` | ✅ |
| License-flip `auth` off → not loaded, fail-closed | `tests/test_auth_e2e.py` | ✅ |

`cd backend; ruff check .; pytest -q` → all green (auth needs no broker).

## Manual
```pwsh
cd backend; python run.py
curl -s -XPOST localhost:8000/auth/login -H "content-type: application/json" `
  -d '{"username":"admin","credential":{"password":"admin"}}'
# -> {token, expires, principal:{role:super_admin, permissions:[...]}}
curl -s localhost:8000/auth/me -H "Authorization: Bearer <token>"
curl -s localhost:8000/auth/users -H "Authorization: Bearer <token>"   # AUTH.MANAGE_USERS
```

## Biometric-readiness — confirmed
A new authenticator is one `Authenticator` class + a config value; sessions,
users, state, audit, the core port, the `credential` record, and
`login(credential: dict)` are unchanged.

## Deferred / known gaps
- **P2.6 UI** (4 React screens) — separate frontend phase (needs a React shell +
  `DATA_TRANSFER.md`).
- **Frozen sidecar packaging (pre-existing, Phase 0).** `python run.py` works in
  dev, but the PyInstaller onefile does not run: `uvicorn.run("core.app:app")`
  imports the app by string (so `core` isn't bundled), and modules + `argon2` are
  imported dynamically via `discover()` (so they + module manifest/schema JSON
  aren't bundled). Fix is its own task: import the app object in `run.py`; add a
  `.spec` that `collect_submodules('modules'/'core')` + `collect_all('argon2')` +
  bundles `modules/**/manifest.json`, `**/schemas/*.json`, `core/schemas/*.json`,
  `config/*.example.json`; update the CI build to use the spec; verify the frozen
  exe's `/modules/status` lists all modules.
- Dev `admin/admin` in `app.example` — provision real users for production.
- `user`/`session`/`credential` excluded from future RAG ingestion.
- Enforcement on Phase-1 control endpoints deferred (use `require_permission`).

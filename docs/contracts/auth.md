# Contract — `auth` (User Authentication)

Centralized, **permission-first** authentication + authorization. Headless
backend module (the React UI is a later phase). Requirement source:
[User_Authentication_Module_Summary.md](../User_Authentication_Module_Summary.md).
Entitlement key `auth`. Fills the `core.auth` port (CORE.md §6.4).

## Principal (resolved at login, rides on every request)
```
Principal = { subject: username, role: str, permissions: frozenset[str], claims: dict }
```
Permissions are resolved from the user's role **at login** and frozen onto the
session. Role changes take effect at **next login** (station-autonomous; no
per-request callback into Auth).

## Permission grammar
`DOMAIN.ACTION`, uppercase, dot-separated. `DOMAIN.*` grants every action in a
domain; `*` grants everything. Matching is wildcard-aware
(`core.services.auth_verify.permission_granted`).

**Domains:** `AUTH, TEST, RECIPE, REPORT, MAINTENANCE, SYSTEM, ADMIN, DIAGNOSTICS`.

**Known actions (extend as modules land):**
| Permission | Used by |
|---|---|
| `AUTH.MANAGE_USERS` | Auth user-management API |
| `TEST.RUN` | runs: run.start/abort |
| `RECIPE.VIEW` | recipe module (read recipes/step-types) |
| `RECIPE.EDIT` | recipe module (author/version) |
| `REPORT.VIEW` | report module (read reports/analytics) |
| `REPORT.EXPORT` | report module (export reports) |
| `MAINTENANCE.CALIBRATE` | maintenance |
| `DIAGNOSTICS.VIEW` | diagnostics stream |
| `DOMAIN.*` | all actions in a domain |

Modules gate routes with `require_permission(*perms)` from
[core/services/security.py](../../backend/core/services/security.py); they consume
**permissions, never roles** (roles live only inside Auth).

## Roles
**One role per user.** Roles → permissions are **data** (config `roles` map); a
customer adds a role by editing config, no code change. Default roles:
`super_admin, admin, engineer, operator, maintenance`.

## Locked rules
- **Permissions, not roles**, across module boundaries.
- **Resolve-at-login**: permission set computed once, on the Principal.
- **Single active session**: a new login revokes the user's prior sessions.
- **Session locality**: sessions are per-station, never bridged to the central
  broker (PRINCIPLES §0).
- **Fail-closed**: no Auth module loaded ⇒ `core.auth` rejects all tokens.

## The pluggable seam
Only the `Authenticator` (credential check) varies; everything else (session,
state machine, audit, port) is fixed. v1: `password` (Argon2) + `no_auth` (dev).
Biometric is future — one `Authenticator` class + a config value, no other change
(biometric-readiness rule). `login` takes `credential: dict` so a biometric
payload needs no contract change.

## User states
`ACTIVE | LOCKED | PASSWORD_RESET_REQUIRED`. Checked **before** the authenticator:
LOCKED → reject; PASSWORD_RESET_REQUIRED → authenticate but force a change.

## Service interface (see api in P2.3/P2.4)
Auth ops: login, logout, change-password, reset-password, validate-session
(`verify`), get-current-user (`/auth/me`), check-permission (`require_permission`).
Audit events on the diag bus: Session Started/Ended, Password Changed, User
Locked/Unlocked.

## Persistence (CORE.md §7, via base Repository — no custom tables)
Record types `user`, `credential`, `session` — **excluded from future RAG
ingestion** (operational + secrets). Shapes in P2.3.

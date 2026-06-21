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

**Domains:** `AUTH, TEST, RECIPE, REPORT, MAINTENANCE, SYSTEM, ADMIN, DIAGNOSTICS, HEALTH`.

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
| `SYSTEM.RESET_DATA` | settings: reset run/test/report data (super_admin only) |
| `SYSTEM.SETTINGS` | settings: MES interlock config + station settings (super_admin) |
| `HEALTH.VIEW` | health: read checks/runs/current/issues |
| `HEALTH.RUN` | health: run non-disruptive checks |
| `HEALTH.MAINTENANCE` | health: run disruptive checks, enter/exit maintenance (R3) |
| `DOMAIN.*` | all actions in a domain |

Modules gate routes with `require_permission(*perms)` from
[core/services/security.py](../../backend/core/services/security.py); they consume
**permissions, never roles** (roles live only inside Auth).

## Roles
**One role per user.** Roles → permissions are **data** (config `roles` map); a
customer adds a role by editing config, no code change. Default roles:
`super_admin, admin, engineer, operator, maintenance`.

### Protected `super_admin` (singleton)
`super_admin` is a protected singleton — the always-available root account:
- **Exactly one** user may hold it; it is **never assignable** (creating a second,
  or promoting another user to `super_admin`, is rejected — 403).
- **Only its password may change** (change-password / admin reset). Lock,
  unlock, activate, deactivate, and role-change are rejected (403).
- **Self-heals on boot**: if it is ever found LOCKED/INACTIVE, the module forces
  it back to ACTIVE at startup — it can never be left locked out.
- **Visible only to a super_admin**: list/get of users hides `super_admin`
  accounts from any non-`super_admin` viewer (as if absent).

### Role-assignment rules (create + role change)
- Roles are chosen from the configured role set, never free text. `GET /auth/roles`
  returns the roles the **current viewer** may assign.
- A role that itself grants `AUTH.MANAGE_USERS` (e.g. `admin`) is **elevated** and
  assignable **only by a `super_admin`** — an `admin` cannot create or promote
  another `admin`. `super_admin` is never assignable. Assigning a role outside the
  viewer's allowed set is rejected (403).
- The whole user-management surface (create/list/lock/role/…) is gated on
  `AUTH.MANAGE_USERS` (held by `super_admin` + `admin` by default) — permission,
  not a role check.

### User creation (temp password + forced change)
- Create takes `{ username, role }` — **no admin-set password**. The server
  generates a temporary password, returns it once to the caller, and starts the
  account in `PASSWORD_RESET_REQUIRED`.
- The new user logs in with the temp password and **must change it on first
  login** before reaching any other screen (`must_change_password`).

### Password policy
Minimum length **5**; no complexity rules. Enforced on change-password only
(creation/reset use a generated temp password).

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
User management (gated `AUTH.MANAGE_USERS`): list/get users, list assignable
roles (`GET /auth/roles`), create (returns temp password), set-role, lock,
unlock, activate, deactivate, reset-password.
Audit events on the diag bus: Session Started/Ended, Password Changed, User
Locked/Unlocked.

## Persistence (CORE.md §7, via base Repository — no custom tables)
Record types `user`, `credential`, `session` — **excluded from future RAG
ingestion** (operational + secrets). Shapes in P2.3.

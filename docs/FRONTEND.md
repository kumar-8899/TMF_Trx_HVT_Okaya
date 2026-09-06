# FRONTEND — the operator web UI

The React app under `frontend/`. It is a **pure client of Python** (REST +
WebSocket on `127.0.0.1:8000`); it never talks to the MQTT broker. This doc is the
map of the UI: stack, theme, shared components, screens, auth, and streaming.

**How it is served.** In dev, Vite (`:5173`) serves the SPA with HMR and proxies the
API to `:8000`. In a shipped station there is no Vite — the **backend serves the
built bundle** on the same `:8000` edge (single origin), so relative API/WS URLs just
work. See [RUNNING.md](RUNNING.md) (`core/services/spa.py`, the `Accept`-header
SPA/API split) and `python station.py` for the one-click launch.

## Stack

- **Vite + React 18 + TypeScript + MUI v5** (`@mui/material`, `@mui/icons-material`).
- Routing: `react-router-dom`. Tests: `vitest` + Testing Library (jsdom).
- Dev proxy: Vite forwards `/…` and `ws:true` to `127.0.0.1:8000`.

```
frontend/src/
  main.tsx            providers (ColorMode → Router → Auth) + App
  App.tsx             routes + permission gating (overridable screens resolve via app/registry)
  api/client.ts       fetch wrapper (bearer token, RFC-7807 → Error.message)
  app/                registry.ts + overrides/ — the APP-OWNED screen-override seam
                      (TEMPLATE.md §1.3): a fork drops overrides/<x>.tsx exporting
                      { key, component } to replace Runs / Recipes / recipe editor /
                      recipe detail / Maintenance; framework ships overrides/ empty
  theme/              theme.ts (tokens), ColorMode.tsx (light/dark provider+toggle)
  components/         Layout (AppBar + drawer), UserMenu, UpdateChip, BrandMark, ui.tsx, RecipeForm, StepEditor
  screens/            Login, ChangePassword, Dashboard, Runs, Recipes,
                      RecipeDetail, RecipeEditor, Reports, Users, ComingSoon
  auth/               AuthContext, permissions.ts, RequirePermission
  hooks/              useStream (WebSocket)
  test/               fetchMock, setup
```

## Theme — "instrument console" (navy / green)

One token set in [`theme/theme.ts`](../frontend/src/theme/theme.ts) drives a
**light** and a **dark** theme via `makeTheme(mode)`; `ColorMode.tsx` provides the
mode + a persisted toggle (localStorage `tmf.colormode`, default **dark**).

| Token | Light | Role |
|---|---|---|
| background.default | `#E8EEF4` | light blue-grey canvas |
| AppBar | `#1C2A3A` | dark-navy app chrome |
| Section header | `#1E3A5F` | navy section/chart header bars |
| primary | `#1A6B3C` | green CTAs (Start, Publish, Save) |
| error | `#9B1C1C` | crimson destructive (Abort) |
| warning | `#E8A020` | amber accent |
| info | `#185FA5` | blue secondary |
| status.pass/fail/running/idle | green/crimson/amber/grey | semantic status |

The dark theme mirrors these hues on a deep-navy canvas. **Status colors are a
separate palette** (`palette.status`, augmented onto MUI) so "running/amber" never
reads as a brand CTA. Cards are white (light) with a subtle shadow + light border;
labels are uppercase muted grey; values are large navy-bold; tables are dense with
uppercase headers. Monospace (`MONO_STACK`) is used for ids, values, and codes.

## Shared components ([`components/ui.tsx`](../frontend/src/components/ui.tsx))

The visual vocabulary every screen reuses:

- `PageHeader{title, subtitle, actions}` — page title row.
- `Section{title, subtitle, actions, bodyPad}` — white card; a **title renders as a
  navy header bar**. `bodyPad={0}` for flush tables.
- `StatusChip{label, kind}` / `StatusDot{kind}` — semantic status; `statusKind(s)`
  maps backend strings (`active/draft/PASS/FAIL/running/connected/…`) to a kind.
  Both fall back to a built-in palette when rendered outside the ThemeProvider
  (so unit tests need no theme).
- `EmptyState`, `ConfirmDialog`.
- `BrandMark` (the app logo — an oscilloscope waveform on a navy tile; also the SVG
  favicon in `index.html`), `Sparkline` (dependency-free SVG trend).

## Shell — AppBar & drawer ([`components/Layout.tsx`](../frontend/src/components/Layout.tsx))

- **AppBar**, grouped left→right: `BrandMark` + app name (+ a fork's client logo,
  issue #7) · Exeliq logo (right) · then, separated by thin dividers,
  **station-readiness lamp** │ **help / full-screen / light-dark** icons │ **`UserMenu`**.
- **`UserMenu`** — the avatar opens a dropdown with the signed-in identity, **Log out**,
  and (super_admin) **Exit station** (the graceful `POST /system/shutdown`). This folds
  what were separate session + power-icon controls into one, to keep the bar uncluttered.
- **Drawer** — the nav is grouped into collapsible sections (Dashboard, Runs top-level;
  then Operations / Health / Config / Administration; Help), permission/role-filtered.
  **`UpdateChip`** ("Relaunch to update") is pinned at the **foot of the drawer**, shown
  only when a signed update is staged.
- **Run lock (#6.5)** — while a run is active the AppBar controls collapse to a
  "TEST IN PROGRESS" label and the brand is inert, so only Abort is reachable.
- **Full-screen (#6.4)** — an AppBar toggle; `station.py --fullscreen` does the same at
  the window level.

## Auth & permissions

- `AuthContext` holds the `Principal {username, role, permissions[]}`, the bearer
  token (localStorage `tmf.token`), login/logout/change-password, and `can(perm)`.
- `permissions.ts#hasPermission` mirrors the backend wildcard rule (`*`,
  `DOMAIN.*`) — **UX only; the API is the real gate** (PRINCIPLES §3).
- `RequirePermission` / nav filtering hide what the user can't use. A
  `must_change_password` principal is routed to Change Password before anything
  else (drives the temp-password-on-first-login flow).

## Streaming (`hooks/useStream.ts`)

`useStream<T>(path | null)` opens a WebSocket to a backend WS endpoint and returns
`{ last, status }`. Pass `null` to stay idle. Used by:
- Runs station feed + live results (`/ws/station`).

## Screens

**Per-app overrides (v1.4.0+):** Runs, Recipes, the recipe editor/detail, and
Maintenance are override-able — an application fork replaces them by dropping a
file in `src/app/overrides/` (default-export `{ key, component }`; keys `runs`,
`recipes`, `recipe-editor`, `recipe-detail`, `maintenance`). `App.tsx` renders
`APP_SCREENS[key] ?? <framework default>`; the permission wrappers stay in the
framework. The framework ships `overrides/` empty. See TEMPLATE.md §1.3.

| Screen | Route | Notes |
|---|---|---|
| Login | `/login` | split navy-identity / white-form card; secure-connection note |
| Change password | `/change-password` | forced on first login (temp password) |
| Dashboard | `/` | attention band (disconnected instruments, offline bridge, unconfigured report DB, skipped modules, pending app update) or an all-clear; 7-day KPI band + pass/fail trend chart; live instrument connection panel |
| Runs (Test Bench) | `/runs` | **operator testing window** — drawer-less layout (AppBar stays); identity (Serial No / Model) + Start dialog (Barcode / Select-recipe) + Abort; big **verdict banner**, message/status line, **live results table**, **live-values** tiles (live-values WS), **today strip** (pass/fail/yield + recent-run dots). Composition driven by `GET /runs/config` |
| Recipes | `/recipes` | list: search/filter/sort, count cards, import/export (`.zip`), per-row View / **Edit** (new version, same id) / **Duplicate** (new editable id) / Export |
| Recipe editor | `/recipes/new`, `/recipes/:id/edit` | two-pane: left rail of tests (search, All/Set/Empty, status dots) + right pane (fixed fields + Parameter Name/Value/Unit table); Owner auto = current user |
| Recipe view | `/recipes/:id` | editor surface **read-only** + versions/compare; **Edit (new version)** (fork→publish, same id) · **Duplicate** (copy → new editable id) · **Deactivate** (deprecate) |
| Reports | `/reports` | per-run report list (Serial · Model · Recipe · Result · Cycle s · Finished); filters (serial search, model dropdown, result, **business-day date range**), **paging** (rows/page + prev/next), row → results dialog + export; **Full view** = flattened test-data matrix (one row/run, a column per test parameter) + **Export CSV (all filtered)** |
| Analytics | `/analytics` | premium dashboard (Recharts): filters (range/model/operator/**shift**) + KPI band + tabs — Quality (FPY p-chart, pass/fail), Failures (Pareto + cumulative, parameter Pareto, by-model, **by-shift**), Cycle time (histogram, I-MR). Day-counts group by **business day** when shifts are enabled. Fed by `GET /reports/analytics/dashboard` |
| Users | `/users` | table with role **dropdowns** + state chips; New-user modal; super_admin hidden from non-super_admins; **Permissions** button (AUTH.MANAGE_ROLES) |
| Permissions | `/permissions` | AUTH.MANAGE_ROLES (super_admin); **role × permission matrix** with allow/disallow checkboxes, grouped by domain; super_admin column read-only; Save (per-role PUT) — applies at users' next login |
| Settings | `/settings` | super_admin only; **Data management** (per-item reset toggles → Reset selected); **Report database** (MySQL/SQL Server provider + connection + Test connection + Save — the pro DB report store); **Remote debugging** (flight-recorder on/off + bind/token + live status → `app.json` `debug.enabled`, applied on relaunch — REMOTE_DEBUG.md) |
| Help | `/help` + AppBar **?** panel | HELP.VIEW; in-app docs from the `help` module. AppBar **?** (or `F1`) opens a **context-aware** slide-over for the current screen; `/help` is the full page (sidebar tree + search + markdown). super_admin gets a **User/Developer** toggle (dev docs gated HELP.DEV). |
| Config (cascaded nav group, `CONFIG.VIEW`) | `/config/*` | **Instruments** (`/config/instruments`) — **owner-aware** form engine: pick **Python-owned** (library picker → fields from the library's `connection_params` in the index + `simulated`) or **LabVIEW-owned** (transport picker → fields from `GET /config/transports`); id/label/model, editable resource + preview, **Test connection** (LabVIEW probe / live instance state), family/capabilities; CRUD gated `CONFIG.EDIT`; read-only libraries + live-instances panel. Python instances feed the variable engine (apply on restart). **Shift** (`/config/shift`) — enabled toggle + editable shift list (label + start, 24h contiguous; current-shift chip). **MES** (`/config/mes`). **Barcode** — placeholder |
| Health | `/health` | HEALTH.VIEW; **Production Readiness** banner (Ready / Warnings / Blocked), **Operator/Technician/Engineer** view toggle, checks grouped by **business function** (Core Software / Production Systems / Test Equipment / External Systems) with impact + what-to-do + known-issue remedy on failure; per-check & suite Re-test, live progress (WS), **Scheduled runs** (startup/shutdown/30-min/daily), **Trend analysis** (MTBF, fail rate, repeated, flaky), history |
| Maintenance | `/maintenance` | HEALTH.MAINTENANCE; enter/exit maintenance, variable read/write (write-gated on maintenance), run a check, live values — composed from existing contracts; embeds the capability-driven **instrument test bench** panel for `super_admin` (hands-on control of Python-owned instruments; no standalone route) |
| Diagnostics | `/diagnostics` | DIAGNOSTICS.VIEW; live event tail (`/diagnostics/stream`) + readiness (`/readyz`) + module status (thin client, no backend) |

### Recipe authoring model (phase 1)

A recipe is an ordered list of **tests**. Each test is a `parametric_test` step:
fixed fields (Test ID, Name, **Test group**, Enabled, Timeout, Retry, On-fail,
Safety-critical) + a flat **Parameter Name / Value / Unit** table. Hovering a test
in the left rail shows a **clone** icon that duplicates it with an incremented
`test_id`. The shared
[`RecipeForm`](../frontend/src/components/RecipeForm.tsx) renders this read/write
(editor) and read-only (view). The richer step-type sequence editor is phase 2;
legacy/other step types still open read-only.

## Dev & test

```pwsh
cd frontend
npm install
npm run dev          # Vite on :5173 (proxy → :8000)
npx vitest run       # unit tests (27)
npm run build        # tsc + production bundle
```
Or the whole stack at once from the repo root: `./dev.ps1` (Vite + HMR), or
`python station.py` (backend serves the built bundle in a native window — it rebuilds
a stale bundle first). See [RUNNING.md](RUNNING.md).

Test conventions: `test/fetchMock.ts` maps `"METHOD /path" → {status, body}`;
components render without a ThemeProvider (status helpers self-fallback). Keep the
stable selectors (aria-labels, button text) that tests assert on.

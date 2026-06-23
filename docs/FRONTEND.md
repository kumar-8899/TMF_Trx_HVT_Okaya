# FRONTEND — the operator web UI

The React app under `frontend/`. It is a **pure client of Python** (REST +
WebSocket on `127.0.0.1:8000`, proxied by Vite in dev); it never talks to the
MQTT broker. This doc is the map of the UI: stack, theme, shared components,
screens, auth, and streaming.

## Stack

- **Vite + React 18 + TypeScript + MUI v5** (`@mui/material`, `@mui/icons-material`).
- Routing: `react-router-dom`. Tests: `vitest` + Testing Library (jsdom).
- Dev proxy: Vite forwards `/…` and `ws:true` to `127.0.0.1:8000`.

```
frontend/src/
  main.tsx            providers (ColorMode → Router → Auth) + App
  App.tsx             routes + permission gating
  api/client.ts       fetch wrapper (bearer token, RFC-7807 → Error.message)
  theme/              theme.ts (tokens), ColorMode.tsx (light/dark provider+toggle)
  components/         Layout, SessionPanel, BrandMark, ui.tsx, Sparkline, RecipeForm, StepEditor
  screens/            Login, ChangePassword, Dashboard, Daq, Runs, Recipes,
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
- `BrandMark` (teal/green app glyph), `Sparkline` (dependency-free SVG trend).

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
- DAQ stream cards (`/instruments/daq/{ai,di}/stream/ws`),
- Runs station feed + live results (`/ws/station`).

## Screens

| Screen | Route | Notes |
|---|---|---|
| Login | `/login` | split navy-identity / white-form card; secure-connection note |
| Change password | `/change-password` | forced on first login (temp password) |
| Dashboard | `/` | station readiness stat cards + module-status grid |
| DAQ | `/daq` | AI/DI stream cards (live channel tiles + sparklines, channel/rate), Variables panel (read/write, DO set 0/1) |
| Runs (Test Bench) | `/runs` | **operator testing window** — drawer-less layout (AppBar stays); identity (Serial No / Model) + Start dialog (Barcode / Select-recipe) + Abort; big **verdict banner**, message/status line, **live results table**, **live-values** tiles (DAQ values WS), **today strip** (pass/fail/yield + recent-run dots). Composition driven by `GET /runs/config` |
| Recipes | `/recipes` | list: search/filter/sort, count cards, import/export (`.zip`), per-row View / **Edit** (new version, same id) / **Duplicate** (new editable id) / Export |
| Recipe editor | `/recipes/new`, `/recipes/:id/edit` | two-pane: left rail of tests (search, All/Set/Empty, status dots) + right pane (fixed fields + Parameter Name/Value/Unit table); Owner auto = current user |
| Recipe view | `/recipes/:id` | editor surface **read-only** + versions/compare; **Edit (new version)** (fork→publish, same id) · **Duplicate** (copy → new editable id) · **Deactivate** (deprecate) |
| Reports | `/reports` | per-run report list (serial), detail dialog with results + export |
| Analytics | `/analytics` | premium dashboard (Recharts): filters (range/model/operator) + KPI band + tabs — Quality (FPY p-chart, pass/fail), Failures (Pareto + cumulative, parameter Pareto, by-model), Cycle time (histogram, I-MR). Fed by `GET /reports/analytics/dashboard` |
| Users | `/users` | table with role **dropdowns** + state chips; New-user modal (role dropdown, temp password shown); super_admin hidden from non-super_admins |
| Settings | `/settings` | super_admin only; **Data management** (per-item reset toggles: runs/reports/logs/recipes/users-except-super_admin → Reset selected), **MES interlock** (gate/publish toggles) |
| Health | `/health` | HEALTH.VIEW; **Production Readiness** banner (Ready / Warnings / Blocked), **Operator/Technician/Engineer** view toggle, checks grouped by **business function** (Core Software / Production Systems / Test Equipment / External Systems) with impact + what-to-do + known-issue remedy on failure; per-check & suite Re-test, live progress (WS), **Scheduled runs** (startup/shutdown/30-min/daily), **Trend analysis** (MTBF, fail rate, repeated, flaky), history |
| Maintenance | `/maintenance` | HEALTH.MAINTENANCE; enter/exit maintenance, variable read/write (write-gated on maintenance), run a check, live values — composed from existing contracts |
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
Or the whole stack at once from the repo root: `./dev.ps1`.

Test conventions: `test/fetchMock.ts` maps `"METHOD /path" → {status, body}`;
components render without a ThemeProvider (status helpers self-fallback). Keep the
stable selectors (aria-labels, button text) that tests assert on.

# Screens tour

Every framework screen, captured from a **pristine simulated station** (default branding, demo data). Each
image shows the framework version it was captured at and warns if the screen's source has changed since —
refresh with `cd tools/screenshots && npm run capture`. Which screens a role can open is in
[Facts & figures](help:dev-guide-facts) (Screens and what they need).

## Operate

![Dashboard](asset:dashboard)

`/` — station readiness, yield/units KPIs, live instrument connection state.

![Runs](asset:runs)

`/runs` — the operator test bench (starts a run; no side menu while a run is active). **Overridable**: an app
replaces it with `frontend/src/app/overrides/runs.tsx`.

![Recipes](asset:recipes)
![Recipe detail](asset:recipe-detail)
![Recipe editor](asset:recipe-editor)

`/recipes` — versioned, controller-native recipes (draft → publish). The editor builds `{type, id, params}`
steps from the [step-type catalog](help:dev-guide-building-blocks). All three are overridable.

![Reports](asset:reports)
![Analytics](asset:analytics)

`/reports`, `/analytics` — per-run reports and yield analytics (business-day aware).

![Health](asset:health)

`/health` — Production Readiness: non-disruptive checks, history, known-issue matching.

## Configure

![App identity](asset:config-branding)
![Instruments](asset:config-instruments)

Config → **Instruments** is the **single source** of instrument instances (with the per-instrument
*Simulated* toggle) — see [Gotchas](help:dev-guide-gotchas).

![Variable map](asset:config-variables)
![Barcode](asset:config-barcode)
![Shift](asset:config-shift)
![MES](asset:config-mes)

## Administer

![Users](asset:users)
![Permissions](asset:permissions)

Permissions are `DOMAIN.ACTION`; the matrix edits role → permission grants at runtime
([defaults](help:dev-guide-facts)).

![Settings](asset:settings)
![Diagnostics](asset:diagnostics)
![Logs](asset:logs)
![Help](asset:help)

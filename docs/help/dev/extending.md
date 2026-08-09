# Extension how-tos

Concrete recipes for the common extensions.

## Add a module
See [Module framework](#). Copy an existing small module (`config`, `mes`) as a template; register, manifest, gate it in config + license, gate routes, write a tester.

## Add a recipe step type
Step types are the **controller's** (v1.3.0 unification): the 8 core types live in
`controller/controller/step_types/` (handler + `schemas/<type>.json`); an application
adds product-specific types as a **step-type package** under its own `app/<name>/`
(handler + schema beside it; loaded via `step_type_packages`). The recipe module
serves the combined catalog at `GET /recipes/step-types` and validates recipes
against it — the editor UI adapts automatically. Author app types with the
`test-step-authoring` skill. (The legacy `modules/recipe/step_types/` path still
validates old recipes but is not surfaced.)

## Override an operator screen (per-app UI)
Runs, Recipes, recipe editor/detail, and Maintenance can be replaced per application
without touching framework files: drop `frontend/src/app/overrides/<x>.tsx`
default-exporting `{ key, component }` (keys: `runs`, `recipes`, `recipe-editor`,
`recipe-detail`, `maintenance`). `src/app/registry.ts` auto-registers it and the
router uses it in place of the framework screen; permission wrappers stay in the
framework. The overrides directory is app-owned (TEMPLATE.md §1.3) — framework
upgrades merge cleanly.

## Add an instrument transport
One entry in `backend/modules/config/transports.py` (`id`, `label`, typed `fields`, `address_template`). The UI renders it automatically — **no frontend change**. LabVIEW handles the actual I/O for that transport.

## Add a health check
Register a `CheckDescriptor` in `modules/health/checks.py` with operator metadata (`purpose`, `impact`, `user_action`, `group`, `severity`). Web checks get a Python executor; bridge/hardware checks dispatch `health.check.<id>` to LabVIEW. Hardware checks are instance-templated.

## Add a permission
Add it to `modules/auth/permissions_catalog.py`, gate the route with `require_permission`, and grant it in role config (or via the Permissions matrix). Remember: permissions resolve **at login**.

## Add a Debug Server signal
The sidecar (`backend/debug_server/`) is bus-only. New derived views go in `analysis.py` + an endpoint in `app.py`. Never make it a runtime dependency of the core.

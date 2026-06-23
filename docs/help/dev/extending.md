# Extension how-tos

Concrete recipes for the common extensions.

## Add a module
See [Module framework](#). Copy an existing small module (`config`, `mes`) as a template; register, manifest, gate it in config + license, gate routes, write a tester.

## Add a recipe step type
Under `modules/recipe/step_types/<name>/`: `schema.json` (envelope-validated) + `type.py`. Add semantic rules in `modules/recipe/validation/semantic.py` if needed. Phase-1 authoring uses `parametric_test`.

## Add an instrument transport
One entry in `backend/modules/config/transports.py` (`id`, `label`, typed `fields`, `address_template`). The UI renders it automatically — **no frontend change**. LabVIEW handles the actual I/O for that transport.

## Add a health check
Register a `CheckDescriptor` in `modules/health/checks.py` with operator metadata (`purpose`, `impact`, `user_action`, `group`, `severity`). Web checks get a Python executor; bridge/hardware checks dispatch `health.check.<id>` to LabVIEW. Hardware checks are instance-templated.

## Add a permission
Add it to `modules/auth/permissions_catalog.py`, gate the route with `require_permission`, and grant it in role config (or via the Permissions matrix). Remember: permissions resolve **at login**.

## Add a Debug Server signal
The sidecar (`backend/debug_server/`) is bus-only. New derived views go in `analysis.py` + an endpoint in `app.py`. Never make it a runtime dependency of the core.

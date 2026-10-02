# Framework facts (generated — do not edit)

Super_Test_App **v1.27.3**. Regenerate: `python tools/gen_devguide.py`.

## Latest releases

- **v1.27.3** (2026-10-03, PATCH) — new-test-app / add-bench-test: ship a verified `run_sim.py` template (PATCH).
- **v1.27.2** (2026-10-03, PATCH) — A fresh install no longer boots with the station offline (PATCH).
- **v1.27.1** (2026-09-29, PATCH) — run_station.exe: also replace Nuitka with PyInstaller (PATCH).
- **v1.27.0** (2026-09-29, MINOR) — Replace Nuitka with PyInstaller for the backend; always bundle app packages; drop dual-scope updates (MINOR).
- **v1.26.1** (2026-09-29, PATCH) — `cut-release.ps1 -Scope`: an app-payload update is now cuttable as its own release (PATCH).
- **v1.26.0** (2026-09-29, MINOR) — Narrow the Nuitka compile surface + app-payload-only patch updates (MINOR).
- **v1.25.0** (2026-09-28, MINOR) — Barcode Start dialog: scan-to-submit is now opt-in, not the unconditional default (MINOR).
- **v1.24.2** (2026-09-28, PATCH) — Downstream fork fixes: a bad instrument no longer kills the whole controller, cycle time reaches reports, and results tables render human-readable (PATCH).
- **v1.24.1** (2026-09-27, PATCH) — Station launcher: maximized by default (not kiosk), and a clean shutdown from the title-bar close button (PATCH).
- **v1.24.0** (2026-09-21, MINOR) — User Portal: a built-in replacement for the printed software manual, with a searchable PDF library (MINOR).

## Modules

| id | version | contract | prefix | permissions |
|---|---|---|---|---|
| auth | 1.0.0 | 1 |  | AUTH.MANAGE_ROLES, AUTH.MANAGE_USERS |
| config | 1.0.0 | 1 |  | CONFIG.EDIT, CONFIG.VIEW |
| health | 1.0.0 | 1 |  | HEALTH.MAINTENANCE, HEALTH.RUN, HEALTH.VIEW |
| help | 1.0.0 | 1 |  | HELP.VIEW |
| logs | 1.0.0 | 1 | /logs | DIAGNOSTICS.PURGE, DIAGNOSTICS.VIEW |
| mes | 1.0.0 | 1 |  | SYSTEM.SETTINGS |
| portal | 1.0.0 | 1 |  | PORTAL.MANAGE, PORTAL.UPLOAD, PORTAL.VIEW |
| recipe | 1.0.0 | 1 | /recipes | RECIPE.EDIT, RECIPE.VIEW |
| report | 1.0.0 | 1 | /reports | REPORT.EXPORT, REPORT.VIEW, SYSTEM.SETTINGS |
| runs | 1.0.0 | 2 |  | SYSTEM.RESET_DATA |
| variables | 1.0.0 | 1 |  | CONFIG.VIEW, HEALTH.MAINTENANCE |

## Permissions

| key | label |
|---|---|
| AUTH.MANAGE_USERS | Manage users |
| AUTH.MANAGE_ROLES | Manage permissions |
| TEST.RUN | Run tests |
| RECIPE.VIEW | View recipes |
| RECIPE.EDIT | Edit recipes |
| REPORT.VIEW | View reports |
| REPORT.EXPORT | Export reports |
| HEALTH.VIEW | View health |
| HEALTH.RUN | Run health checks |
| HEALTH.MAINTENANCE | Maintenance mode |
| MAINTENANCE.CALIBRATE | Calibrate |
| CONFIG.VIEW | View config |
| CONFIG.EDIT | Edit config |
| DIAGNOSTICS.VIEW | View diagnostics |
| DIAGNOSTICS.PURGE | Purge logs |
| HELP.VIEW | View user docs |
| HELP.DEV | View developer docs |
| PORTAL.VIEW | Use the user portal |
| PORTAL.UPLOAD | Add portal documents |
| PORTAL.MANAGE | Manage the portal |
| SYSTEM.RESET_DATA | Reset data |
| SYSTEM.SETTINGS | Station settings |

## Roles (default grants)

- **admin**: AUTH.MANAGE_USERS, TEST.RUN, RECIPE.VIEW, RECIPE.EDIT, REPORT.VIEW, REPORT.EXPORT, DIAGNOSTICS.VIEW, HEALTH.VIEW, HEALTH.RUN, HEALTH.MAINTENANCE, CONFIG.VIEW, CONFIG.EDIT, HELP.VIEW, PORTAL.VIEW, PORTAL.UPLOAD, PORTAL.MANAGE
- **engineer**: TEST.RUN, RECIPE.VIEW, RECIPE.EDIT, REPORT.VIEW, REPORT.EXPORT, DIAGNOSTICS.VIEW, HEALTH.VIEW, HEALTH.RUN, CONFIG.VIEW, CONFIG.EDIT, HELP.VIEW, PORTAL.VIEW, PORTAL.UPLOAD
- **maintenance**: MAINTENANCE.CALIBRATE, DIAGNOSTICS.VIEW, HEALTH.VIEW, HEALTH.RUN, HEALTH.MAINTENANCE, CONFIG.VIEW, CONFIG.EDIT, HELP.VIEW, PORTAL.VIEW
- **operator**: TEST.RUN, RECIPE.VIEW, REPORT.VIEW, REPORT.EXPORT, HEALTH.VIEW, CONFIG.VIEW, HELP.VIEW, PORTAL.VIEW
- **super_admin**: AUTH.*, TEST.*, RECIPE.*, REPORT.*, MAINTENANCE.*, SYSTEM.*, ADMIN.*, DIAGNOSTICS.*, HEALTH.*, CONFIG.*, HELP.*, PORTAL.*

## Step types

| type | kind | composite |
|---|---|---|
| group | primitive | True |
| if | primitive | True |
| measure_and_compare | primitive | False |
| prompt_operator | primitive | False |
| repeat | primitive | True |
| set_output | primitive | False |
| sweep | primitive | True |
| wait | primitive | False |

## Instrument capabilities

- **dso** v1 (non-scalar): configure, capture
- **analog_input** v1 (scalar): read_voltage
- **digital_input** v1 (scalar): read_digital
- **digital_output** v1 (scalar): write_digital, read_digital_setpoint
- **electronic_load** v1 (scalar): set_mode, set_setpoint, load_enable, measure_voltage, measure_current, measure_power
- **frequency** v1 (scalar): measure_frequency
- **power_source** v1 (scalar): set_voltage, get_voltage_setpoint, measure_voltage, measure_current, set_current_limit, output_enable
- **resistance** v1 (scalar): measure_resistance
- **safety_tester** v1 (non-scalar): measure_ir, measure_acw
- **temperature** v1 (scalar): measure_temperature
- **multiplexer** v1 (non-scalar): set_route, open_all, get_routes

## Controller MQTT ops

| op | group | blocking |
|---|---|---|
| daq.ai.read | daq | False |
| daq.ai.stream.start | daq | False |
| daq.ai.stream.stop | daq | False |
| daq.di.read | daq | False |
| daq.di.stream.start | daq | False |
| daq.di.stream.stop | daq | False |
| hello.echo | core | False |
| instrument.call | instruments | True |
| instrument.status | instruments | False |
| instrument.test | instruments | True |
| maintenance.enter | maintenance | False |
| maintenance.exit | maintenance | False |
| run.abort | runs | False |
| run.start | runs | False |
| safety.clear | safety | False |
| safety.status | safety | False |
| safety.trip | safety | False |
| sequencer.list_test_classes | runs | False |
| variable.read | instruments | True |
| variable.read_many | instruments | True |
| variable.write | instruments | True |

## Frontend routes

| path | needs |
|---|---|
| * |  |
| / |  |
| /analytics | REPORT.VIEW |
| /change-password |  |
| /config/barcode | CONFIG.VIEW |
| /config/branding | super_admin |
| /config/instruments | CONFIG.VIEW |
| /config/mes | CONFIG.VIEW |
| /config/shift | CONFIG.VIEW |
| /config/variables | super_admin |
| /diagnostics | DIAGNOSTICS.VIEW |
| /health | HEALTH.VIEW |
| /help | HELP.VIEW |
| /login |  |
| /logs | DIAGNOSTICS.VIEW |
| /maintenance | HEALTH.MAINTENANCE |
| /permissions | AUTH.MANAGE_ROLES |
| /portal | PORTAL.VIEW |
| /recipes | RECIPE.VIEW |
| /recipes/:id | RECIPE.VIEW |
| /recipes/:id/edit | RECIPE.EDIT |
| /recipes/new | RECIPE.EDIT |
| /reports | REPORT.VIEW |
| /runs | TEST.RUN |
| /settings | SYSTEM.RESET_DATA |
| /users | AUTH.MANAGE_USERS |

## Skills

- **add-bench-test** — Guided workflow to add or build a test (or a whole test sequence) IN AN EXISTING forked test application on the Super_Test_App framework, in
- **clone-test-app** — Start a new test application by cloning an EXISTING forked app (on the Super_Test_App framework) that is similar to what's needed, instead o
- **create-instrument-library** — Author a new Python instrument library into the Instrument_Library repo (a local clone at $TMF_INSTRUMENT_LIBRARY) against a capability inte
- **new-test-app** — Fork the Super_Test_App test-and-measurement framework into a new, self-contained test application. Use when the user wants to create/scaffo
- **system-blueprint** — Turn a filled "System Blueprint" Excel workbook into a test application's canonical I/O artifacts — the controller-side variable map (app/<n
- **test-step-authoring** — Author a new test step type for the Python Test Controller — the handler, its parameter schema, a simulated DUT, and the tests that exercise

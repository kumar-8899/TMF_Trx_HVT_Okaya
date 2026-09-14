# Contract — `runs` (Runs)

Controller run-control proxy + run-record persistence + station/diag fan-out.
LabVIEW owns execution; this module relays control and turns controller events
into durable records (CORE.md §7). One variant: `default`. Entitlement key `runs`.

## Acquisition (which recipe to run)
A run learns its recipe either from a **barcode** (EOL benches — a configured part of
the barcode encodes the model/recipe id) or a **directly chosen recipe id** (endurance
benches — operator picks from a list). Whether the Start dialog shows a barcode/serial
field or a recipe dropdown, and how a scanned barcode resolves to a recipe id, is owned
entirely by the **`config` module's Barcode page** (`docs/contracts/CONFIG.md` §Barcode),
not by this module — `runs` just delegates:

```python
result = await core.get_contract("config").resolve_recipe_from_barcode(barcode)
# {"ok": True, "recipe_id": ..., "parts": {...}} or {"ok": False, "error": ...}
```

This is a **soft** cross-module call (`try/except KeyError` around `get_contract`, the
same idiom `_delegate_reset` uses) — `runs` does not declare `config` in
`contract_dependencies`, since module activation has no topological sort and `runs`
activates before `config` in `app.json`'s module list; a hard dependency would silently
skip-activate the whole module at boot. A `{"ok": False}` result or an absent `config`
module both raise `AcquisitionError` → HTTP 422.

### Bench profile (operator window)
The operator testing window is **config-driven**: `GET /runs/config` returns a
declarative profile so the window's composition changes by config, not code.
```json
{ "identity": { "model": "prefix", "serial": "barcode" },
  "live_variables": [ { "name": "vbus_main", "label": "DC Bus", "unit": "V", "format": "0.0" } ],
  "analytics": { "daily": true },
  "ui": { "verdict_banner": true, "message_line": true, "today_strip": true } }
```
`identity` derives **Model** (= resolved recipe id) and **Serial No** (= full `barcode`)
at run start; both are written to `run_parameters` and the run record. `live_variables`
are streamed to the window over the DAQ values WS (`/instruments/values/ws`). Daily
pass/fail uses `GET /reports/analytics?since=<midnight>`.

## Commands issued (Py → LV)
- `run.start` `{ run_id, recipe_id, version?, run_parameters? }` — Python resolves
  the recipe id (direct or from a barcode), **mints `run_id`**, and starts. LabVIEW
  then pulls the run-parameter-substituted recipe JSON via `query/recipe.fetch`
  (RECIPE §11). A scanned `barcode` is folded into `run_parameters`.
- `run.abort` `{}`.

## Subscriptions (LV → Py)
`event/#` (persisted + fanned out), `diag` (fanned out). Event kinds consumed:
`run-started`, `run-finished` (`result` = PASS|FAIL|ABORTED), `run-aborted`,
`step-*`, `safety-*`, and **`test-result`** rows.

### `test-result` event
One result row per event (multiple may arrive during a run):
```json
{ "type": "test-result", "ts": 0,
  "payload": { "run_id": "…", "serial_no": 1, "test_name": "OVP trip",
               "expected": "320 V", "measured": "319.4 V", "result": "PASS",
               "cycle_time_ms": 412 } }
```

## Persistence (CORE.md §7, base Repository)
- Every `run-*` / `step-*` / `safety-*` / `test-result` event → an append-only
  `run_event` record.
- The current-state `run` record (keyed by `run_id`) is **merged** across the
  lifecycle: `run_start` pre-creates it (`starting`, `recipe_id`); `run-started`
  → `running`; `run-finished`/`run-aborted` → `finished` (+ `result`, ABORTED for
  aborted); each `test-result` appends to the record's `results[]` array. The RAG
  envelope is stamped automatically.

## HTTP / WS surface
| Method | Path | Behaviour |
|---|---|---|
| GET  | `/runs/config` | bench profile (identity + live_variables + analytics + ui) for the operator window |
| POST | `/runs/start` | body `{ recipe_id? \| barcode?, version?, run_parameters? }` → resolve + mint run_id + `run.start`; returns `{ run_id, recipe_id }` |
| POST | `/runs/abort` | `run.abort` |
| GET  | `/runs` | run records (`since`, `limit`) |
| GET  | `/runs/{id}` | one run record incl `results[]` (404 if absent) |
| WS   | `/ws/station` | fan-out of all `event/*` envelopes (incl `test-result`) |
| WS   | `/diagnostics/stream` | fan-out of `diag` events |

## Standalone test
`core + runs + stub bridge + :memory: db` —
`backend/modules/runs/tester/test_runs.py` (control commands, lifecycle →
records, non-run ignored, WS fan-out). Live gate:
`python -m tools.check_phase1 --no-stub`.

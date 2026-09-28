# CONFIG — station configuration centre

The `config` module backs the cascaded **Config** menu: a home for operator-editable
station configuration, each concern its own scalable section — **Instruments**,
**Shifts**, **Barcode**. **MES** (the interlock controls) is its own top-level module,
mounted separately, since it has runtime behavior beyond pure configuration.

It is a **pure config surface** — it captures connection profiles and asks LabVIEW
to probe them. It performs **no instrument I/O itself** (PRINCIPLES §0: hardware is
LabVIEW's).

## Shifts (business day + labels)

The **Shift** section configures the production schedule and, with it, the
**business day** analytics group by.

- Config: `{enabled, shifts:[{label, start "HH:MM"}]}` (DB record `shift_config`).
- **Locked model:** shifts **tile 24h contiguously** — each runs to the next shift's
  start; the last wraps past midnight. The **business day rolls at the first (earliest)
  shift's start**, so an overnight shift belongs to the calendar date it **started**
  on. A run/report is assigned by its **start** time.
- `shift_for(ts) -> {enabled, business_day, shift_label, index}` and `current_shift()`
  live on the config module (contract + `GET /config/shift`, `PUT /config/shift`,
  `GET /config/shift/current`). Disabled/none → `business_day` is the calendar date,
  `shift_label` null.
- **Report stamping (forward-only):** on run-finish the report module stamps
  `business_day` + `shift_label` (via `config.shift_for(run_start_ts)`). Analytics
  group day-counts by `business_day` (fallback calendar date for old reports) and add
  a **shift** filter + `by_shift` breakdown. The Test Bench shows the current shift.

## Barcode (structure + recipe-id extraction)

The **Barcode** section defines the shape of the barcode/label an operator scans or
types at run-start, and which slice of it is the recipe id.

- Config: `{enabled, length, parts:[{name, start, length}], recipe_part, submit_on_enter}`
  (DB record `barcode_config`, fixed id `"barcode"` — one global record, like Shifts, not
  per-station: barcode format is a labeling-scheme fact, not per-socket wiring).
  `length` is the barcode's total, exact-match-validated length; each `parts[]` entry is
  a named fixed-width slice (`start`/`length` offsets into the barcode string);
  `recipe_part` names which part's extracted value is used **directly** as the
  `recipe_id` (no indirection through `recipe.barcode_prefixes` — that mechanism is
  separate and unused by this path). Validated on save: `length >= 1`; each part's name
  non-empty + unique, `start >= 0`, `length >= 1`, `start+length <= length`; when
  `enabled`, at least one part exists and `recipe_part` references one of them.
  `submit_on_enter` (bool, default `false`) gates whether Enter in the Start dialog's
  serial-number field starts the run: a real barcode scanner appends Enter to every scan
  (keyboard-emulation, on by default on virtually every scanner), so the default keeps
  "scan" and "start the test" two separate actions — the operator reviews the resolved
  recipe preview and clicks Start explicitly. Set `true` only for a bench where nothing is
  gained by that review beat (framework-fix-prompt-2.md Issue 1).
- `resolve_recipe_from_barcode(barcode) -> {"ok": True, "recipe_id", "parts": {name: value}}`
  or `{"ok": False, "error"}` lives on the config module (contract + `GET /config/barcode`,
  `PUT /config/barcode`) — it's how `runs` resolves a scanned barcode to a recipe id
  (`docs/contracts/runs.md` §Acquisition), returning an envelope rather than raising,
  since it's called across the module boundary. It does not verify the recipe id exists;
  that happens later, when the recipe is actually fetched.
- **Drives the Start dialog directly:** when `enabled`, the operator sees one serial/
  barcode field (recipe auto-resolved from `recipe_part`); when not, one recipe dropdown
  (operator picks manually). No manual mode switch — the config's `enabled` flag is the
  only thing that decides which the operator sees.
- This replaced the old `runs.acquisition.barcode.strategy` (`prefix`/`fixed`) mechanism,
  which had no operator UI and could only express "first N chars" or "always this one
  recipe" (v1.19.0 — CHANGELOG).

## Instrument ownership (one registry, two owners)

Every instrument declares one **execution owner** (INSTRUMENT_LIBRARY §0 — disjoint):

- **`owner: "labview"`** (default) — LabVIEW does the I/O. The **transport-driven**
  form (below); `test connection` is dispatched to LabVIEW over the bridge.
- **`owner: "python"`** — a **Python-owned** instrument backed by an `instrumentlib`
  library. The form is driven by the chosen **library's `connection_params`** (from
  the library index), plus a `simulated` flag. Validated against the registry
  (unknown library / missing required param → 422). `test connection` reports the
  **live instance state** from the variable engine (edits **apply on restart**).
  Under a supervised Python controller (`controller.kind=="python"`), that state is
  a live poll of the controller's own connection (`instrument.status`,
  PYTHON_CONTROLLER.md §7) — the backend never opens its own; under `"labview"` the
  variable engine connects directly at startup, as it always has.

The `config` module is the **single instrument registry** (DB `instrument` records) —
one source of truth for the *config*. The `variables` (variable-engine) module consumes
`config.python_instruments()` at startup to build its instances, but that is only "no
duplication" of records; it is not a claim that only one process ever talks to the
device. **Exactly one process ever holds the LIVE connection**, and which one depends on
`controller.kind`: the supervised controller when `"python"` (the backend proxies through
it instead of connecting itself — the fix for a real bug where both connected
independently and a single-client instrument's loser stuck at "disconnected" forever), or
the backend itself when `"labview"` (no controller subprocess exists to proxy through).
Non-scalar capabilities appear in the variable map as **actions**, never signals
(INSTRUMENT_LIBRARY §2.2).

**Multi-station (`MULTI_STATION.md` §4.3):** each instrument record carries `stations[]`
(a single-station value migrates to a one-element list). The instruments form gains a
stations multi-select. For any instance shared across sockets (`len(stations) > 1`), the
**no-lease binding rule** (`PYTHON_CONTROLLER.md` §9.3) is enforced at save **and** startup,
loudly — a read-only signal is allowed; a signal with `write`, or any non-scalar `action`,
is **refused**. It prevents a configure-then-read interleaving across sockets from
producing a silent wrong PASS. A shared NI-DAQ card serving four stations passes cleanly
(AI reads are stateless); a shared source bound for write does not.

## Why a transport-driven UI (the scalability contract)

Instruments differ by transport (VISA, Modbus, CAN, NI-DAQmx, …). Rather than a
bespoke form per type, the backend ships a **transport catalog** and the UI renders
**one generic form** from it. Adding a new instrument type = **one catalog entry**
([`transports.py`](../../backend/modules/config/transports.py)), zero UI code.

### Transport descriptor

```
{ id, label, address_template,
  fields: [ { key, label, type, required, default?, placeholder?, help?, options? } ] }
```
`type` ∈ `string | number | password | select` (select carries `options`).
`address_template` previews the canonical resource via `str.format` over the
params (e.g. VISA `{resource}`, Modbus TCP `{host}:{port} (unit {unit_id})`,
NI-DAQmx `{device}/{channel}`). Shipped transports: `visa`, `modbus_tcp`,
`modbus_rtu`, `can`, `nidaq`, `serial`, `raw_tcp`.

### Instrument record (transport-agnostic)

Stored as a DB record (type `instrument`, operator-editable — not app.json):
```
{ id, label, model, transport, params{}, address, family, capabilities[], enabled }
```
`family`/`capabilities` are the shape the **health** module templates hardware
checks against (§4.4 there) — so a configured instrument can later drive its own
health checks. (Health still reads `instances` from its own config today; the
linkage is the planned next step.)

## API (prefix `/config`)

| Method | Path | Perm | Purpose |
|---|---|---|---|
| GET | `/config/transports` | CONFIG.VIEW | the catalog that drives the form |
| GET | `/config/instruments` | CONFIG.VIEW | list instruments |
| POST | `/config/instruments` | CONFIG.EDIT | create (id `^[a-z][a-z0-9_]{0,63}$`, unique) |
| GET | `/config/instruments/{id}` | CONFIG.VIEW | one instrument |
| PUT | `/config/instruments/{id}` | CONFIG.EDIT | update |
| DELETE | `/config/instruments/{id}` | CONFIG.EDIT | delete |
| POST | `/config/instruments/test` | CONFIG.VIEW | probe a saved id or ad-hoc `{transport, params}` |

## Test connection (the LabVIEW seam)

`POST /config/instruments/test` dispatches bridge op **`instrument.test`**
`{transport, params, address}` → LabVIEW attempts the connection (and `*IDN?`-style
identity where it can) → `{ok, status, identity?, detail}`. **Honest verdicts**: when
the bridge is offline the result is `unavailable` (never a hang), mirroring the
health seam. LabVIEW must answer `instrument.test` (see LABVIEW_BRIDGE.md).

## Permissions

`CONFIG.VIEW` (read + test), `CONFIG.EDIT` (create/update/delete). super_admin
holds `CONFIG.*`; admin/engineer/maintenance get VIEW+EDIT; operator VIEW.

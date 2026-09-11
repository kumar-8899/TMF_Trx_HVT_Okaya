# CONFIG — station configuration centre

The `config` module backs the cascaded **Config** menu: a home for operator-editable
station configuration, each concern its own scalable section. First section:
**Instruments**. Planned: **Barcode**, **Shift**, and **MES** (the MES interlock
controls moved here from Settings).

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

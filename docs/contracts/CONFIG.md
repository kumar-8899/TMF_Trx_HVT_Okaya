# CONFIG — station configuration centre

The `config` module backs the cascaded **Config** menu: a home for operator-editable
station configuration, each concern its own scalable section. First section:
**Instruments**. Planned: **Barcode**, **Shift**, and **MES** (the MES interlock
controls moved here from Settings).

It is a **pure config surface** — it captures connection profiles and asks LabVIEW
to probe them. It performs **no instrument I/O itself** (PRINCIPLES §0: hardware is
LabVIEW's).

## Instrument ownership (one registry, two owners)

Every instrument declares one **execution owner** (INSTRUMENT_LIBRARY §0 — disjoint):

- **`owner: "labview"`** (default) — LabVIEW does the I/O. The **transport-driven**
  form (below); `test connection` is dispatched to LabVIEW over the bridge.
- **`owner: "python"`** — a **Python-owned** instrument backed by an `instrumentlib`
  library. The form is driven by the chosen **library's `connection_params`** (from
  the library index), plus a `simulated` flag. Validated against the registry
  (unknown library / missing required param → 422). `test connection` reports the
  **live instance state** from the variable engine (Python instruments connect at
  startup — edits **apply on restart**).

The `config` module is the **single instrument registry** (DB `instrument` records).
The `variables` (variable-engine) module consumes `config.python_instruments()` at
startup to build its instances — one source of truth, no duplication. Non-scalar
capabilities are never bound in the variable map (INSTRUMENT_LIBRARY §2.2).

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

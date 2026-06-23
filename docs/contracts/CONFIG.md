# CONFIG — station configuration centre

The `config` module backs the cascaded **Config** menu: a home for operator-editable
station configuration, each concern its own scalable section. First section:
**Instruments**. Planned: **Barcode**, **Shift**, and **MES** (the MES interlock
controls moved here from Settings).

It is a **pure config surface** — it captures connection profiles and asks LabVIEW
to probe them. It performs **no instrument I/O itself** (PRINCIPLES §0: hardware is
LabVIEW's).

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

# System Blueprint

The **System Blueprint** is an Excel authoring surface a test engineer fills in to declare
one application's **I/O system** — its instruments and every input/output signal with the
address relative to an instrument — and a deterministic generator that turns it into the
framework's canonical artifacts.

It is an **app-authoring aid shipped with the framework** (like the skills). The framework
itself is not a system and never fills one in; only a real application does. Tooling:
`backend/tools/blueprint/`; skill: `system-blueprint`.

## 1. What it is — and is not

- **Defines topology, not tests.** Instruments + signals + their addresses. No recipes, no
  step types. Recipes reference the signal *names* it produces, later.
- **Authoring input, never runtime data.** The generator emits the same
  `app/<name>/maps/<station>.json` the controller's variable engine loads — exactly as if
  hand-authored. Nothing reads the workbook at runtime; it is not a second source of truth.
- **The `.xlsx` is generated, owned, and disposable.** The generator script
  (`tools/blueprint/template.py`) is the source of truth in git; a blank workbook is
  produced on demand. A *filled* workbook belongs to the app (or the engineer) — do not
  commit it into the framework repo.

## 2. The `tag` rule (the reconcile key)

Every row on every sheet carries a short, unique **`tag`** the author assigns once and
**never changes**. It is the key the generator reconciles on. Because identity lives in the
tag — not the row position or the display name — a fuller sheet supplied later can
**update in place** (fill blanks, rename by tag, add new rows) instead of clobbering work
already built from an earlier partial sheet.

## 3. Progressive fill-in

You need not know everything up front. Leave a cell blank or write `TBD` for what is not
known yet. A signal with **no `read` and no `write` method** is tracked as **pending** and
**not emitted** to the map (the engine requires a direction), so a later sheet completes it
without the intermediate state producing a broken binding.

## 4. The sheets

The columns match exactly what the generator reads. Closed-vocabulary columns get Excel
dropdowns; capability-method columns are free text validated against the live catalog
(`backend/modules/variables/capabilities.py`) since their legal values depend on the row's
instrument.

### Instruments — one row per instrument instance
`tag` · `id` (`^[a-z][a-z0-9_]{0,63}$`, defaults from tag) · `label` · `owner`
(`labview`|`python`) · `model` · `family` · `library` (python-owned; a library_id) ·
`transport` (labview-owned; from `backend/modules/config/transports.py`) · `connection`
(→ `params`, as `key=value; key=value`) · `capabilities` (python: from the library;
labview: free) · `stations` (blank = all) · `simulated` (python; default `true`) ·
`status` (`known`|`TBD`|`removed`) · `notes`.

Instrument instances are **DB records** created on **Config → Instruments** — the generator
cannot create them. It emits `docs/INSTRUMENTS.md` as the setup checklist, plus a
paste-ready `controller.json` `instances` block for standalone / sim runs (that list is
ignored under app supervision — see CONFIG.md).

### Signals — one row per scalar variable
`tag` · `name` (`^[a-z][a-z0-9_]{0,63}$`) · `station` (which map file; default `st1`) ·
`instrument_tag` (FK → Instruments.tag) · `read` (capability read method) · `write`
(capability write method) · `channel` (the **fixed leading args** = the sub-address;
comma-separated for multi-arg methods) · `units` · `gain` · `offset` (→ `scale`) ·
`clamp_min` · `clamp_max` (bound writes) · `range_min` · `range_max` (expected read range;
Debug-Server logging) · `deadband` · `status` · `notes`.

**Direction is derived, never entered:** a `read` method makes the signal an input, a
`write` method an output, both a bidirectional. The generated binding is the controller-side
shape `{instance, read?, write?, args?, scale?, clamp?, units?}` (+ `range`/`deadband`
metadata) — see `controller/controller/instruments/variables.py`.

### The address model
"Address relative to an instrument" has two regimes, chosen by the instrument's `owner`:

- **Python-owned** → address = **capability method + `channel`** (the fixed args). e.g.
  `dut_resistance` = `dmm.measure_resistance(104)`. The generator validates the method
  against the instrument's capabilities and checks the channel/arg **arity** against the
  engine's calling convention (a read passes all args; a write appends the value last).
- **LabVIEW-owned** → address = the **transport `params`** (a VISA resource, `Dev1/ai0`, a
  `host:port`). LabVIEW-owned signals are captured as an **inventory** only; they are not
  emitted to the controller-side map (they reach Python as MQTT telemetry — LABVIEW_BRIDGE.md).

### Actions — non-scalar capabilities (optional)
`tag` · `name` · `station` · `instrument_tag` · `capability` · `notes`. Non-scalar
capabilities (`multiplexer`, `dso`) are reached via `capability.request`, never bound as a
signal (INSTRUMENT_LIBRARY.md).

### Multiplexing — scanned / relay-switched readings
The framework deliberately keeps multiplexing **out of the variable map** (a binding is a
single call; `multiplexer` is non-scalar; sequencing lives inside the driver). So a shared
reader scanned across many points via relays is realized as a **composite driver**: each
scan point is an **ordinary Signals row** on the composite instrument (e.g.
`cell_3_voltage → cell_scanner.read_voltage(3)`), a first-class logged, limit-checked
variable. The relay switching + settle live **inside** that driver.

A **digital output that only steers the mux is a selector element, not a signal** — it never
appears on the Signals sheet. It is captured here:

`tag` · `logical_signal` (→ a Signals `name`) · `measure_instrument_tag` · `measure_method`
· `measure_channel` (the shared reader) · `selector_instrument_tag` · `select_by`
(`mux_route`|`relay_pattern`) · `route` (position) · `relay_pattern` (DO states, e.g.
`do0=1,do1=0,do2=1`) · `settle_ms` · `notes`.

The generator writes `docs/MULTIPLEXING.md` — the position→(relay-pattern + settle +
measurement point) build spec — grouped per composite instrument. Hand it to the
**`create-instrument-library`** skill to build the driver.

## 5. Generation & reconcile

```
python -m tools.blueprint make-template  <path.xlsx>
python -m tools.blueprint generate --workbook <path.xlsx> --app-name <name> [--root <repo>]
                                   [--prune] [--dry-run]
```

Outputs under `app/<name>/`: `maps/<station>.json`, `maps/.blueprint.lock.json` (the tag
ledger), `docs/INSTRUMENTS.md`, `docs/MULTIPLEXING.md` (if any scan rows), and
`blueprint-report.md`. `generate` exits `2` on blocking validation errors and **writes
nothing** in that case — the report lists what to fix.

Reconcile (keyed on `tag`, against the ledger):
- **Added** — a new tag.
- **Changed** — a tag whose name/station (rename/move) or binding changed. A rename updates
  the map in place; it never duplicates.
- **Removed** — a tag dropped from the sheet. **Kept-and-warned** by default (it may be
  referenced by a recipe); pass `--prune` — only on explicit confirmation — to delete it.
- **Pending** — a signal still missing a read/write method; tracked, not emitted.

The map is **owned** by the blueprint: edit the **sheet** and regenerate rather than
hand-editing the map, so the ledger stays authoritative. The generator never touches
framework-owned files, recipes, step types, or UI overrides.

## 6. Where it fits

`new-test-app` scaffolds the app; `system-blueprint` fills/regenerates the variable map from
a spreadsheet — usually after the fork exists, and repeatedly as the I/O is nailed down.
`create-instrument-library` builds any composite (multiplexing) driver the blueprint
specifies. Validation vocabularies are read live from the framework code, so the template
never drifts from what the engine accepts.

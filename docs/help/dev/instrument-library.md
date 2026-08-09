# Python instrument library (framework core)

Implements `INSTRUMENT_LIBRARY.md`. This is the **framework-core half**: the fat
base, capability interfaces, deterministic fault transport, the registration
decorator + index generator, and the **conformance suite**. Per-instrument library
classes live in a **separate repo** (`D:\Experiment\Instrument_Library`) and are
gated by this suite as external subjects.

## Where it lives
```
backend/instrumentlib/
  errors.py        structured errors (never return a wrong value)
  interfaces.py    capability interfaces (§2) — power_source, electronic_load,
                   analog/digital in/out, temperature; multiplexer, dso (non-scalar)
  transport.py     Transport ABC · SimTransport · FaultTransport + FaultPlan (§7)
  base.py          InstrumentBase — lock, state machine, invoke, reconnect,
                   emergency fan-out (§3)
  registry.py      @instrument_library + build_index() (§5.1, §10)
  conformance.py   run_all(cls, make) — the §8 battery (the existence gate)
```

## The one call path
Consumers (variable engine, `capability.request`) call **`instance.invoke(method, …)`** —
never the raw method. `invoke` gives, for free: per-instance lock, fail-fast if not
`connected` (never queues), per-command timeout, automatic diagnostics
`(instance_id, method, args, elapsed_ms, outcome)`, structured error mapping, and —
on a transport disconnect — a background backoff reconnect that re-verifies identity
(`on_reconnect`) before returning to `connected` (mismatch → `faulted`).

## Fault injection (§7)
Five deterministic primitives in the transport (`after_n`, `once`, glob match):
`timeout · disconnect · garbage · delay_ms · error_response`. Libraries are unaware;
they experience faults as real misbehaviour. The same plan file is a reproduction
harness.

## Adding a library (in the library repo)
1. `class Foo(InstrumentBase, IPowerSource)` — implement the interface's methods
   using `self.transport`; put all command strings in a **class-level `CMD` dict**
   near the top (the 5-minute manual diff).
2. `@instrument_library(library_id=…, capability="power_source", interface_version=1,
   transports=[…], library_version=…, generated_by=…, manual_reference=…)`.
3. Implement `identify`, `safe_state`, `emergency_disable`; set `EXPECTED_IDN`.
4. Must pass **conformance** (`run_all`) in sim — not green ⇒ **not in `index.json`**
   ⇒ does not exist to the builder or a deployment.

## Rules a library MUST obey
One primary capability; zero class/module mutable state (the `CMD` dict is a
constant); device errors + implausible reads surface as **structured errors, never
values**; never import another library, touch the bridge, or emit diagnostics (the
base does it).

## Variable engine (IL2)
The `variables` module (`backend/modules/variables/`) is the surviving ~200 lines
(§5.3): a name → `{instance, read/write, scale, clamp, units}` map over instances it
builds from config via the instrumentlib registry (double-open guard; unknown library
skipped loudly). Read = `raw*gain+offset`; write = clamp (logged + returned) → inverse
scale → `invoke`. Serves `variable.read/write/read_many/write_many` to LabVIEW over the
bridge (Py-served `query/{op}`) plus REST (`GET /variables`,
`GET`/`PUT /variables/{name}/value`, `POST /variables/{read,write}`). Reads gated
`CONFIG.VIEW`, writes `HEALTH.MAINTENANCE`. Unbound variable names fail readiness.

## Status
- **IL1 — done:** base + interfaces + fault transport + registry/index + conformance.
- **IL2 — done:** variable engine + instance registry + bridge verbs + REST + readiness.
- **IL3 — done:** the library repo (`D:\Experiment\Instrument_Library`) — VISA transport,
  first library (Keysight E36xx `IPowerSource`), conformance-over-every-library tests,
  `ci.py` emitting `index.json`. Pinned to this core via `conftest`/`ci` sys.path.
- **IL4 — done:** the `variables` module loads the library package (config
  `library_paths` + `library_packages`) so instances **bind**; `capability.request`
  seam (bridge + `POST /variables/instances/{id}/call`); `GET /variables/libraries`
  (the index) + `GET /variables/instances` (live state); the Config → Instruments page
  shows available libraries + live instances; health check `instruments.python`
  reports any Python-owned instance not connected.

## Wiring an application to the library repo

**Application forks need no wiring (v1.4.1+):** the variables module auto-discovers
the repo-root `instrument_libs/` (the drivers a fork copied from the central
`Instrument_Library`, TEMPLATE.md §1.2) and imports it — the copied drivers appear
in the Instruments page's Library dropdown automatically.

**Instances come from the Instruments page (v1.5.0+):** the page's records
(owner=python, enabled) are the single source of instrument instances for the whole
app — the variable engine AND the supervised Python controller. Nothing reaches an
instrument (even simulated) until configured there; each instrument runs simulated
or real by its own **Simulated** toggle (v1.5.1+ — no app-level switch).

The explicit `variables` module config below remains for dev setups and tests
(inline `instances` build in addition to the page's records):
```json
"config": {
  "library_paths": ["D:/Experiment/Instrument_Library"],
  "library_packages": ["instrument_libs"],
  "instances": [ { "id": "psu_1", "library": "keysight_e36xx", "simulated": true,
                   "params": { "resource": "TCPIP0::…::INSTR" } } ],
  "variables": { "psu_vout": { "instance": "psu_1", "read": "measure_voltage",
                               "write": "set_voltage", "units": "V",
                               "clamp": { "min": 0, "max": 30 } } }
}
```
`library_paths` is a path pin today (becomes a pip dependency once the core is packaged).

## Packaging & pinning the core
The core ships as the distribution **`tmf-instrumentlib`** (nested
`backend/instrumentlib/pyproject.toml`; version = `base_version`, §9). Build + publish:
```pwsh
cd backend/instrumentlib
python -m build                      # -> dist/tmf_instrumentlib-<ver>-py3-none-any.whl (+ .tar.gz)
# private index:  twine upload dist/*     then depend on  tmf-instrumentlib==<ver>
```
Library repos depend on the **pinned** package, not the source path — the sibling
`Instrument_Library` vendors the wheel in `wheelhouse/` (`--find-links wheelhouse` +
`tmf-instrumentlib==1.0.0`) so it installs standalone. Core devs use
`pip install -e backend/instrumentlib` for live edits.

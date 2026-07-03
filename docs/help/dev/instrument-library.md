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

## Status
- **IL1 (this):** base + interfaces + fault transport + registry/index +
  conformance. 15 tests incl. the full battery against a reference sim subject.
- **IL2 (next):** variable engine (name → `instance.method` + scale/clamp), instance
  registry, `variable.read/write` over the bridge, `GET /variables`.
- **IL3:** the library repo + first real library + CI emitting `index.json`.
- **IL4:** `capability.request` seam + the Instruments config page consuming the
  index + per-instance health checks.

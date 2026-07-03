# INSTRUMENT_LIBRARY.md — Python Instrument Libraries

This document is the contract for the **Python-owned instrument layer**: per-instrument
library classes, the shared base they ride on, the thin variable engine that names their
signals, the conformance machinery that gates them, and the CI pipeline that packages them.

It supersedes the Layer 1–4 machinery of `HAL.md` (driver registry TOML catalog, generic
protocol drivers, endpoint address compilation, four-dispatcher taxonomy) **for the Python
side**. The capability-interface idea from `HAL.md` §6.2 survives and is promoted to the
central contract. `VARIABLE_ENGINE.md` survives in reduced form (§5 of this doc).

Read `PRINCIPLES.md` first. This doc implements its §1 (variation is data), §5 (RAG-ready
records), and §6 (testers as we go, debug-first, no machinery without need).

---

## 0. Locked decisions

| Decision | Choice |
|---|---|
| **Library economics** | One explicit Python class per instrument model, AI-generated against a capability interface + the vendor manual. No TOML-driven generic drivers. Code-per-instrument is cheap when AI writes it; the interface is the generation contract. |
| **Ownership** | Every physical instrument is owned by exactly one process. Python-owned instruments are reached only through this layer; LabVIEW-owned instruments only through their DQMH request events. An instrument MUST NOT appear in both. LabVIEW-owned values reach Python only as one-way published telemetry on `value/#`, never as a device read. |
| **Seam** | Two MQTT verbs. Scalar named signals: `variable.read / write / read_many / write_many` through the variable engine. Non-scalar actions (mux routing, DSO capture, and any future non-scalar capability): `capability.request(instance, method, args)`, bypassing the variable engine. |
| **Variable engine** | Retained as a ~200-line routing table (name → instance.method + scale/clamp). It exists so recipes name signals, never hardware. It is not a subsystem. |
| **Thin library, fat base** | Libraries contain only device-specific knowledge. All cross-cutting behavior lives in `InstrumentBase`. |
| **Conformance suite location** | **Framework core repo.** The suite is contract enforcement; contracts belong to the platform, not the implementations. The suite version is coupled to `base_version`; libraries are external test subjects. |
| **Namespace disjointness** | Enforced by mechanism (different APIs per owner) + declared as data (execution owner field in the library declaration / station config), not by runtime gate. |

---

## 1. Position in the architecture

```
LabVIEW  (sequencer · safety reflexes · LabVIEW-owned instruments · hardware-timed I/O)
   │
   │  MQTT (per-station loopback broker, via the Bridge singleton)
   │    variable.read / write / read_many / write_many      ← scalar signals
   │    capability.request(instance, method, args)          ← non-scalar actions
   ▼
Python
   variable map        name → instance.method + gain/offset/clamp     (one JSON file)
   station config      instance_id → library_id + connection params   (one JSON file)
   instrument libs     one class per model, implementing a capability
                       interface, riding InstrumentBase
```

Latency-critical and safety-reflex instruments are LabVIEW-owned end to end and never
appear in this layer. The reflex invariant from the ownership discussion is restated here
as a MUST: **an instrument with a safety reflex MUST have that reflex execute
LabVIEW-locally and MUST NOT depend on the variable engine, this library layer, or the
bridge being available for the reflex to fire.**

---

## 2. Capability interfaces — the generation contract

Interfaces are the spec AI codes against, the checklist humans review against, and the
surface everything else calls against. A library implements exactly one primary capability
interface (plus the mandatory `InstrumentBase` surface).

### 2.1 Scalar capability interfaces (reachable via the variable engine)

```
IPowerSource:
    set_voltage(volts)                get_voltage_setpoint() → volts
    measure_voltage() → volts         measure_current() → amps
    set_current_limit(amps)           output_enable(on: bool)

IElectronicLoad:
    set_mode(mode: "cc"|"cv"|"cr"|"cp")
    set_setpoint(value)               load_enable(on: bool)
    measure_voltage() → volts         measure_current() → amps
    measure_power() → watts

IAnalogInput:                         # non-DAQ sources only (instrument readbacks)
    read_voltage(channel) → volts

IDigitalInput:                        # non-DAQ sources only
    read_digital(channel) → bool

IDigitalOutput:                       # non-DAQ sources only
    write_digital(channel, state: bool)
    read_digital_setpoint(channel) → bool

ITemperature:
    measure_temperature(channel) → degrees
```

NI-DAQmx analog/digital I/O is LabVIEW-owned and does not appear here.

### 2.2 Non-scalar capabilities (reachable via `capability.request` only)

```
Multiplexer:
    set_route(channel, bus)           open_all()
    get_routes() → [ {channel, bus} ]

DSO:
    configure(timebase, channels, trigger, …)
    capture() → WaveformRecord        # samples[], dt, t0, units, channel meta
```

Non-scalar capabilities MUST NOT be bound in the variable map. The sequencer commands
them directly by instance id. New non-scalar capabilities follow the same rule.

### 2.3 Interface evolution

- New methods are added with a default implementation that raises `NotSupported` (or a
  capability flag readable by the builder/tester), so existing libraries keep working.
- Every interface carries an `interface_version` integer. Removing or renaming a method
  is a version bump and a breaking change; adding with a default is not.

---

## 3. InstrumentBase — the fat base

Everything below is implemented **once**, in the base. A library MUST NOT reimplement
any of it. This list is also the checklist for what a future cross-cutting feature edit
touches (one file, O(1)).

| Concern | Base behavior |
|---|---|
| **Per-instance lock** | One mutex per instance object. Every command acquires it. No command racing on the wire. |
| **Connection state machine** | `disconnected → connecting → connected → reconnecting`. Exponential backoff 1→2→4→8 s capped at 30 s. State transitions published as diagnostics events and reflected in instance status. |
| **Fail-fast on dead link** | A call issued while not `connected` fails immediately with a structured error. Commands are NEVER queued for later delivery. |
| **`on_reconnect()` hook** | Called by the base after a successful reconnect. The library MUST re-verify identity (`*IDN?` or equivalent matches expected) and re-apply safe state. Restoring prior setpoints is permitted only if the library explicitly declares it safe. |
| **`safe_state()` / `emergency_disable()`** | Mandatory methods. `emergency_disable()` MUST cut all outputs; the platform fans it out in parallel (`gather`) across every registered instance. |
| **Diagnostics emit** | Every command automatically emits `(instance_id, method, args summary, elapsed_ms, outcome)` to the diagnostics bus. Zero per-library effort. |
| **Timeout enforcement** | Per-command timeout owned by the base transport; a timed-out command is a structured error, never a hang. |
| **Simulation mode** | `simulated=true` at construction: connect is a no-op, reads return plausible values, writes are recorded in an inspectable sim state. Part of the interface contract, verified by conformance. |
| **Fault injection** | §7. Lives in the base transport; libraries are unaware of it. |
| **Provenance** | `generated_by`, `manual_reference`, `library_version` carried in the declaration and stamped into diagnostics context. |

---

## 4. Library authoring rules (the AI generation prompt contract)

A generated library MUST:

1. Implement exactly one capability interface from §2, plus the `InstrumentBase`
   mandatory surface (`on_reconnect`, `safe_state`, `emergency_disable`, sim behavior).
2. Hold **zero module-level or class-level mutable state**. All state in `__init__`.
3. Concentrate all command strings / register maps in a **command table near the top of
   the class** — not scattered through method bodies. This is what makes the human
   review a five-minute diff against the vendor manual.
4. Map device-level errors (SCPI error queue, Modbus exceptions) to structured errors.
   A corrupted or implausible reading MUST surface as an error, never as a value —
   a silently wrong number poisons a PASS/FAIL verdict.
5. Declare itself via the registration decorator (§5.1) with full provenance.
6. Never import another library, never touch the bridge, never emit diagnostics
   directly (the base does it).

The generation prompt template is: *"Here is `<ICapability>` (methods + semantics). Here
is the `<vendor manual reference>`. Here are rules 1–6. Implement."*

---

## 5. Registration, index, config, and the variable engine

### 5.1 In-code declaration → generated index

```
@instrument_library(
    library_id       = "chroma_63600",
    vendor           = "Chroma",
    model            = "63600",
    capability       = "electronic_load",
    interface_version= 1,
    transports       = ["visa_lan"],
    connection_params= {"ip": "string", "port": {"type": "int", "default": 5025}},
    library_version  = "1.0.0",
    generated_by     = "claude-code/2026-07",
    manual_reference = "Chroma 63600 Programming Manual v2.3",
)
class Chroma63600(InstrumentBase): ...
```

CI imports the package tree (decorators fire; duplicate `library_id` fails loudly) and
emits **`index.json`** — the machine-readable catalog the builder app, the config form
(`instruments.md` page), and the generic tester all consume. The index is a build
artifact, never hand-authored. Drift is structurally impossible.

### 5.2 Station config (deployment data)

```json
{
  "schema_version": 1,
  "instances": [
    { "id": "load_1_st1", "library": "chroma_63600", "station": 1,
      "params": { "ip": "192.168.10.31" }, "simulated": false },
    { "id": "load_2_st1", "library": "chroma_63600", "station": 1,
      "params": { "ip": "192.168.10.32" }, "simulated": false }
  ]
}
```

Cloning = standard instantiation: N entries, N objects, each with its own connection,
state, and lock. The instance registry MUST reject a duplicate resolved resource string
at startup (the in-process double-open guard). The `instance_id` — not the resource — is
the public name carried by `capability.request`, diagnostics, and health.

### 5.3 The variable map (the surviving 200 lines)

```json
{
  "schema_version": 1,
  "variables": {
    "output_current": { "instance": "load_1_st1", "read": "measure_current",
                        "scale": { "gain": 1.0, "offset": 0.0 }, "units": "A" },
    "dc_bus_setpoint": { "instance": "dc_main_st1", "write": "set_voltage",
                         "read": "get_voltage_setpoint",
                         "clamp": { "min": 0.0, "max": 400.0 }, "units": "V" }
  }
}
```

Read: lookup → capability call → `raw*gain+offset`. Write: clamp (silent, logged as
warning; the returned written-value lets a step detect clamping) → inverse scale →
capability call. That is the entire engine. Recipes and the sequencer reference variable
names only; a vendor swap is one station-config edit and zero recipe changes.

Startup reconciliation: LabVIEW validates every variable name it references against
`GET /variables` at bring-up; an unbound name blocks `/readyz`, loudly.

---

## 6. Reconnect policy (normative)

1. Link loss → state `reconnecting`, backoff loop begins, status event emitted.
2. Any call during `reconnecting`/`disconnected` fails fast with a structured error.
   The sequencer decides (retry step / fail step / abort). No queuing, ever.
3. On physical reconnect → base calls `on_reconnect()`:
   identity re-verified; mismatch → hard error, instance marked faulted.
   Safe state re-applied. Only then does state return to `connected`.
4. All transitions visible on the diagnostics bus and to health checks.

Rationale: after a link drop the device state is unknown (possible power cycle, lost
setpoints). A write executed late, or a resumed session with an output enabled at a
stale voltage, is a hazard — not a convenience.

---

## 7. Fault injection — a transport-layer contract

Faults live in the base transport. Libraries never branch on fault mode; they experience
injected faults exactly as real hardware misbehavior.

### 7.1 Fault plan schema (data, injectable per transport instance)

```json
{
  "faults": [
    { "on": "write", "match": "VOLT*", "action": "timeout",        "after_n": 3 },
    { "on": "read",  "match": "*",     "action": "garbage",        "payload": "\\xFF\\x00" },
    { "on": "any",   "match": "*",     "action": "disconnect",     "once": true },
    { "on": "write", "match": "OUTP*", "action": "delay_ms",       "value": 2000 },
    { "on": "read",  "match": "MEAS*", "action": "error_response",
      "payload": "-113,\"Undefined header\"" }
  ]
}
```

### 7.2 The five primitives

| Primitive | Simulates | Exercises |
|---|---|---|
| `timeout` | no response | fail-fast + timeout enforcement |
| `disconnect` | link drop mid-exchange | reconnect state machine + `on_reconnect` |
| `garbage` | malformed response | parsing robustness; error-not-value rule |
| `delay_ms` | slow device | timeout budget; no event-loop stalls |
| `error_response` | device-level error | error mapping to structured errors |

### 7.3 Rules

- **Deterministic first.** `after_n`, `once`, and command-pattern matching. A conformance
  test asserts "the third `VOLT` write times out" and checks the exact behavior.
  A `probability` field MAY be added later without breaking the schema.
- A fault plan file is also a **reproduction harness**: a field failure becomes a
  committed plan that replays it, paired with the diagnostics timeline.
- Consumers: conformance suite, health-check validation, training/demo mode,
  regression reproduction. One mechanism, four uses.

---

## 8. Conformance suite — the gate

**Location: framework core repo**, versioned with `base_version`. One parametrized
pytest suite runs against **every** registered library as an external subject.

The battery, per library:

1. Interface compliance — implements its declared capability fully; `NotSupported`
   defaults acceptable only where flagged.
2. No module/class-level mutable state.
3. Lock present and honored (concurrent-call test).
4. Sim mode — connect no-op, plausible reads, inspectable writes.
5. Fault battery — all five §7 primitives × the library's command surface:
   fail-fast on timeout, no queuing across disconnect, reconnect + identity
   re-verification, structured error mapping, garbage never surfaces as a value.
6. `safe_state()` / `emergency_disable()` present and effective in sim.
7. Declaration completeness — provenance, params schema, versions.

**The gate rule: a library that does not pass is not in `index.json`. It does not exist
to the builder, the tester, or a deployment.** Human review is thereby reduced to the
one thing machinery cannot check: command strings vs. the vendor manual (the §4.3
command-table rule keeps that review to minutes).

---

## 9. Versioning — three axes

| Axis | Owner | Bumps when |
|---|---|---|
| `interface_version` | capability contracts (this doc) | interface breaking change |
| `base_version` | `InstrumentBase` + conformance suite | base behavior change |
| `library_version` | each library | any library change |

Compatibility rule: a library pins an `interface_version`; the base declares a supported
range; the suite for base vN runs against every library claiming compatibility. All
three axes travel in `index.json`, so the **builder app refuses an incompatible bundle
at packaging time** — fail at build, never at station startup.

---

## 10. CI pipeline (the factory)

Per commit to the library repo:

```
import tree (decorators fire; duplicate library_id → fail loudly)
  → conformance suite × every library
  → fault battery × every library
  → emit index.json (identity, capability, params schema, 3 versions, provenance)
  → package versioned library bundle for the builder app
```

Operational metric: wall-clock from "new instrument on the bench" to "green in the
index". Target: under one day. If it creeps toward a week, some cost above has leaked
O(N) human effort.

## 11. Scope exclusions (deliberate)

No runtime plugin loading, no networked library-registry service, no per-library
processes. Libraries are a Python package, imported at startup, versioned with git,
gated by CI. Revisit only on a demonstrated need (e.g. third-party authors whose code
cannot be merged).

---

## 12. MUST summary

1. One owner per physical instrument; ownership declared as data; no dual access.
2. One primary capability interface per library; non-scalar capabilities never in the
   variable map.
3. Zero mutable module/class state in libraries; all cross-cutting behavior in the base.
4. Fail-fast on dead link; never queue commands; identity re-verified on reconnect.
5. Device errors and implausible readings surface as structured errors, never values.
6. `safe_state()` / `emergency_disable()` mandatory; platform fans out in parallel.
7. Deterministic fault injection in the transport; libraries unaware of it.
8. Conformance pass is the existence condition: not green → not in the index.
9. Three-axis versioning; incompatibility fails at packaging time.
10. `index.json` is generated, never authored.

---

## Open items (block the relevant build phase until resolved)

- **WaveformRecord shape** for the DSO capability (samples encoding on the MQTT wire —
  inline JSON array vs. reference to a sidecar payload; matters above ~100 k points).
- **`capability.request` MQTT topic/verb grammar** — must align with the Bridge
  request/reply convention (correlation_id + reply_to) already locked in
  `LABVIEW_BRIDGE.md`; the exact topic naming is unresolved.
- **Setpoint-restore whitelist** — which capabilities may declare restore-after-reconnect
  safe (loads in CC mode? never for power sources?). Default: nothing restores.

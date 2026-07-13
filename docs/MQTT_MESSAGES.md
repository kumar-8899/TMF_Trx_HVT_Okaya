# MQTT_MESSAGES.md — Complete LabVIEW ↔ Python message reference

Every message on the station bus, both directions, with request + reply examples. This
is the exhaustive catalogue; `LABVIEW_BRIDGE.md` is the contract/rationale behind it
(topic tree, envelopes, liveness, re-implementer rules). Read that first for the *why*;
use this for the *exact wire shapes*.

Station id `st1` is used in every example — substitute your station. All JSON is the
message **payload** (what MQTT Explorer shows as the message body).

---

## 0. Mechanics (read once)

**Topic scoping.** Everything is under `tmf/<station>/…`. The Bridge singleton prefixes
it; callers pass the sub-topic.

**Three message classes:**

| Class | Topic | Direction | Reply? |
|---|---|---|---|
| **Command** | `cmd/<op>` | Python → LabVIEW (LabVIEW serves) | yes → `reply_to` |
| **Query** | `query/<op>` | LabVIEW → Python (Python serves) | yes → `reply_to` |
| **Publish** | `event/#`, `value/#`, `status`, `diag`, `state/#`, `stream/#` | mostly LabVIEW → Python | no |

**Request/reply envelope (both `cmd` and `query`).** The requester publishes a payload
carrying a correlation `id` and a `reply_to` topic; the responder publishes the reply to
that `reply_to` with the **same `id`**:

Request (to `cmd/<op>` or `query/<op>`):
```json
{ "id": "7f3a0091c2", "op": "run.start", "args": { "...": "..." },
  "reply_to": "tmf/st1/cmd/resp/tmf-py-1a2b3c" }
```
Reply (to the `reply_to` topic):
```json
{ "id": "7f3a0091c2", "ok": true, "result": { "...": "..." } }
```
Error reply:
```json
{ "id": "7f3a0091c2", "ok": false,
  "error": { "code": "query_failed", "message": "…", "detail": "" } }
```
(MQTT 5 also sets `ResponseTopic`/`CorrelationData` as an optimization, but the payload
`id`+`reply_to` is authoritative so a 3.1.1 responder works.)

**QoS/retain.** Commands/queries/events: **QoS 1, retain false**. `value/#` + `status`:
**retained** (last value survives; `status` is also the LWT). `stream/#`: QoS 0/1,
**never captured by the Debug Server** and never bridged fleet-wide.

**Index of ops** (details below): Py→LV `hello.echo, run.start, run.abort,
instrument.test, maintenance.enter, maintenance.exit, variable.read, variable.write,
sequencer.list_test_classes, health.check.<id>` · LV→Py queries `recipe.fetch,
variable.read, variable.write, variable.read_many, variable.write_many,
capability.request` · LV→Py publishes `event/<type>, value/<name>, status, diag,
state/maintenance`.

---

## 1. Python → LabVIEW commands (`cmd/<op>`)

Python is the requester; LabVIEW serves and replies to `reply_to`.

### 1.1 `hello.echo` — bridge round-trip probe
Purpose: prove the link + measure latency + clock skew (used by health `bridge.*`).
Topic: `tmf/st1/cmd/hello.echo`
```json
// request args
{ "from": "health" }
// reply result (LabVIEW echoes + stamps its clock)
{ "id": "…", "ok": true, "echoed": { "from": "health" }, "ts": 1748513761.234 }
```

### 1.2 `run.start` — start a test run
Purpose: LabVIEW loads the recipe and runs the sequence.
Topic: `tmf/st1/cmd/run.start`
```json
// request args (run_parameters carry the resolved identity)
{ "run_id": "7f3a-0091", "recipe_id": "INV",
  "run_parameters": { "barcode": "INV12345", "serial_no": "INV12345", "model": "INV" } }
// reply
{ "id": "…", "ok": true, "result": { "run_id": "7f3a-0091", "accepted": true } }
```

### 1.3 `run.abort` — abort the active run
Topic: `tmf/st1/cmd/run.abort`
```json
// request args
{}
// reply
{ "id": "…", "ok": true, "result": { "aborted": true } }
```

### 1.4 `instrument.test` — probe a LabVIEW-owned instrument (Config → Instruments)
Purpose: open the device and read its identity, for the "Test connection" button.
Topic: `tmf/st1/cmd/instrument.test`
```json
// request args
{ "transport": "visa", "params": { "resource": "TCPIP0::192.168.10.31::inst0::INSTR" },
  "address": "TCPIP0::192.168.10.31::inst0::INSTR" }
// reply
{ "id": "…", "ok": true, "status": "pass",
  "identity": "Keysight,E36313A,MY59001234,1.0", "detail": "connected" }
```
Offline bridge → Python returns `{status:"unavailable"}` without sending (honest, never
hangs).

### 1.5 `maintenance.enter` / `maintenance.exit` — request maintenance mode
Purpose: LabVIEW owns maintenance; Python only requests. LabVIEW replies AND publishes
the retained `state/maintenance` (see §4.5). It refuses `enter` while a run is active.
Topic: `tmf/st1/cmd/maintenance.enter` / `…/maintenance.exit`
```json
// enter request args
{ "operator": "admin", "reason": "calibration" }
// reply
{ "id": "…", "ok": true, "accepted": true }
// exit request args
{ "operator": "admin" }
```

### 1.6 `variable.read` / `variable.write` — a LabVIEW-owned variable (DAQ module)
Purpose: Python reads/writes a **LabVIEW-owned** signal (e.g. a DAQ channel) on demand.
(Contrast §2.2 — the *same op names* run LabVIEW → Python for Python-owned instruments.)
Topic: `tmf/st1/cmd/variable.read` / `…/variable.write`
```json
// read request args
{ "name": "vbus_main" }
// read reply
{ "id": "…", "ok": true, "result": { "value": 264.0, "ts": 1748513761.2 } }
// write request args
{ "name": "do_relay1", "value": 1 }
```

### 1.7 `sequencer.list_test_classes` — discover LabVIEW test classes
Purpose: the recipe authoring UI lists the step/test classes LabVIEW offers.
Topic: `tmf/st1/cmd/sequencer.list_test_classes`
```json
// request args
{}
// reply
{ "id": "…", "ok": true, "result": { "classes": ["Measure", "Sweep", "RampUntil"] } }
```

### 1.8 `health.check.<id>` — run a bridge/hardware health check on LabVIEW
Purpose: a check with no Python executor is dispatched to LabVIEW, one per check id
(instance id passed for hardware). Reply is a **CheckVerdict**.
Topic: `tmf/st1/cmd/health.check.bridge.queue_depth` (or `…hardware.self_test`, …)
```json
// request args (instance-templated hardware checks include instance_id)
{ "instance_id": "dmm0" }
// reply — CheckVerdict body
{ "id": "…", "ok": true,
  "status": "pass", "summary": "queue depth 2", "data": { "depth": 2 }, "error": null }
```
Absent LabVIEW handler / offline bridge → Python records `unavailable`/`timeout`.

---

## 2. LabVIEW → Python queries (`query/<op>`)

LabVIEW is the requester; Python serves and replies to `reply_to`. Python wraps the
result as `{ id, ok, result }` (or `{ id, ok:false, error }`).

### 2.1 `recipe.fetch` — LabVIEW pulls a recipe to execute
Topic: `tmf/st1/query/recipe.fetch`
```json
// request args
{ "recipe_id": "INV", "version": null, "run_parameters": { "serial_no": "INV12345" } }
// reply result — the resolved recipe document
{ "id": "…", "ok": true, "result": {
    "recipe_id": "INV", "name": "Inverter EOL", "model": "INV", "version": 3,
    "content_hash": "sha256:…",
    "steps": [ { "step_id": "ovp", "step_type": "parametric_test",
                 "params": { "parameters": [ { "name": "Vtrip", "value": 320, "unit": "V" } ] } } ] } }
```

### 2.2 `variable.read` / `variable.write` — Python-owned instrument scalars (variable engine)
Purpose: the LabVIEW sequencer commands **Python-owned** instrument signals by name;
the variable engine maps name → instance.method + scale/clamp (INSTRUMENT_LIBRARY §5.3).
Topic: `tmf/st1/query/variable.read` / `…/variable.write`
```json
// read request args
{ "name": "psu_vout" }
// read reply result (raw*gain+offset)
{ "id": "…", "ok": true, "result": { "name": "psu_vout", "value": 12.0, "raw": 12.0, "units": "V" } }
// write request args
{ "name": "psu_vout", "value": 5.0 }
// write reply result (clamp applied + reported)
{ "id": "…", "ok": true,
  "result": { "name": "psu_vout", "written": 5.0, "requested": 5.0, "clamped": false } }
```

### 2.3 `variable.read_many` / `variable.write_many`
Topic: `tmf/st1/query/variable.read_many` / `…/variable.write_many`
```json
// read_many request args
{ "names": ["psu_vout", "psu_iout"] }
// read_many reply result
{ "id": "…", "ok": true, "result": {
    "psu_vout": { "name": "psu_vout", "value": 12.0, "raw": 12.0, "units": "V" },
    "psu_iout": { "name": "psu_iout", "value": 0.5, "raw": 0.5, "units": "A" } } }
// write_many request args
{ "values": { "psu_vout": 5.0, "psu_ilim": 1.0 } }
```

### 2.4 `capability.request` — non-scalar instrument action (mux, DSO, …)
Purpose: non-scalar actions bypass the variable engine and address an instance by id
(INSTRUMENT_LIBRARY §2.2).
Topic: `tmf/st1/query/capability.request`
```json
// request args
{ "instance": "mux_1", "method": "set_route", "args": [3, "busA"] }
// reply result
{ "id": "…", "ok": true,
  "result": { "instance": "mux_1", "method": "set_route", "result": null } }
```

---

## 3. LabVIEW → Python — published events (`event/<type>`, no reply)

Published to `tmf/st1/event/<type>`. Each carries the enveloped shape
`{ type, ts, trace?, payload }` (the `payload` object is shown). The `runs` + `report`
modules consume these; a `run_id` groups a run's life.

### 3.1 `run-started`
```json
// tmf/st1/event/run-started
{ "type": "run-started", "ts": 1748513700.0, "trace": "run:7f3a-0091",
  "payload": { "run_id": "7f3a-0091", "recipe": "INV", "recipe_id": "INV", "version": 3 } }
```

### 3.2 `test-result` — one test/parameter outcome
```json
// tmf/st1/event/test-result
{ "type": "test-result", "ts": 1748513712.4,
  "payload": { "run_id": "7f3a-0091", "serial_no": "INV12345", "test_name": "OVP",
               "expected": "320", "measured": "319.4", "result": "PASS", "cycle_time_ms": 412 } }
```

### 3.3 `step-completed` — legacy step outcome (with measurements)
```json
// tmf/st1/event/step-completed
{ "type": "step-completed", "ts": 1748513712.5,
  "payload": { "run_id": "7f3a-0091", "step_id": "s1", "status": "PASSED", "elapsed_ms": 120,
               "measurements": [ { "name": "vbus", "value": 264.0, "units": "V" } ] } }
```

### 3.4 `run-finished`
```json
// tmf/st1/event/run-finished
{ "type": "run-finished", "ts": 1748513760.0, "trace": "run:7f3a-0091",
  "payload": { "run_id": "7f3a-0091", "result": "PASS" } }
```

### 3.5 `run-aborted`
```json
// tmf/st1/event/run-aborted
{ "type": "run-aborted", "ts": 1748513740.0,
  "payload": { "run_id": "7f3a-0091", "reason": "operator abort" } }
```

### 3.6 `safety-trip` — safety reflex fired (no run_id required)
```json
// tmf/st1/event/safety-trip
{ "type": "safety-trip", "ts": 1748513741.0, "payload": { "reason": "overvoltage" } }
```

### 3.7 `heartbeat`
```json
// tmf/st1/event/heartbeat
{ "type": "heartbeat", "ts": 1748513761.0, "payload": {} }
```

---

## 4. LabVIEW → Python — retained/published state (no reply)

### 4.1 `value/<name>` — live variable value (RETAINED)
Purpose: bare, retained latest value; the DAQ values WS + Test Bench live tiles read it.
NOT enveloped, NOT correlated.
```json
// tmf/st1/value/vbus_main   (retain=true)
{ "value": 264.0, "ts": 1748513761.2 }
```

### 4.2 `status` — link liveness (RETAINED + LWT)
Purpose: the bridge is "online" only when this retained topic says so; the broker
publishes the LWT (offline) if LabVIEW dies.
```json
// tmf/st1/status   (retain=true; LWT set to {"state":"offline"})
{ "state": "online" }
```

### 4.3 `diag/<subsystem>` (or `diag`) — DiagnosticEvent
Purpose: LabVIEW's structured diagnostics (LABVIEW_DIAG_EMIT.md). Captured by the Debug
Server + persisted by the logs module. Core consumers subscribe the single `diag` topic;
publish there (subsystem in the payload).
```json
// tmf/st1/diag
{ "seq": 8841, "ts": 1748513761.234, "level": "info", "subsystem": "daq",
  "message": "connect ok", "context": { "resource": "Dev1", "elapsed_ms": 12.4 },
  "exception": null, "station": "st1", "source_version": "labview/1.4.0",
  "trace": "run:7f3a-0091" }
```

### 4.4 `stream/<signal>` — high-rate stream (NOT captured)
Purpose: fast AI/DI streams for the DAQ viewer; latest-wins, never persisted, never
bridged fleet-wide, never captured by the Debug Server.
```json
// tmf/st1/stream/ai
{ "channel": "ai0", "samples": [263.9, 264.1, 264.0], "dt": 0.001, "t0": 1748513761.0 }
```

### 4.5 `state/maintenance` — maintenance mode (RETAINED)
Purpose: the source of truth the UI reads for maintenance state. LabVIEW publishes it
after accepting an `enter`/`exit` command (§1.5).
```json
// tmf/st1/state/maintenance   (retain=true)
{ "state": "on", "since": 1748513761, "by": "admin", "reason": "calibration" }
// cleared
{ "state": "off" }
```

---

## 5. Testing a message by hand (MQTT Explorer)

- **Simulate LabVIEW status/values:** publish retained `tmf/st1/status {"state":"online"}`
  and `tmf/st1/value/vbus_main {"value":264.0,"ts":…}`.
- **Answer a Python command:** subscribe `tmf/st1/cmd/#`; when a request appears, copy its
  `id` + `reply_to`, then publish `{ "id": "<that id>", "ok": true, "result": {…} }` to the
  `reply_to` topic.
- **Send an event:** publish `tmf/st1/event/run-finished {"type":"run-finished","ts":…,"payload":{"run_id":"E1","result":"PASS"}}`.
- Or run the **Debug Server** (`.\debug.ps1 -NoAuth`) to see every message on one
  correlated timeline.

See also: `LABVIEW_BRIDGE.md` (contract), `LABVIEW_DIAG_EMIT.md` (diag library),
`INSTRUMENT_LIBRARY.md` (variable engine + capability.request), `HEALTH_CHECK.md`
(`health.check.<id>`), `DEBUG_SERVER.md` (bus capture).

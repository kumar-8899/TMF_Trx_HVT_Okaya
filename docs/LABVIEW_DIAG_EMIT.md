# LABVIEW_DIAG_EMIT.md — The Unified Diag-Emit VI Library (LabVIEW §7)

This document is the **implementation spec** for the LabVIEW client library named
in `DEBUG_SERVER.md` §7. It is the LabVIEW-side companion to the Debug Server: one
small library inside each DQMH module that publishes structured diagnostic events
to the MQTT bus via the Bridge singleton.

Build against this doc together with `DEBUG_SERVER.md` §4 + §7, `LOGGING.md` §2.3
(the `DiagnosticEvent` shape), and `LABVIEW_BRIDGE.md` (the Bridge singleton +
topic scoping). It introduces **no** new transport — the bus you already have is
the only wire.

---

## 0. Scope & locked decisions

| Decision | Choice | Why |
|---|---|---|
| **Transport** | Rides the **Bridge singleton**. No own MQTT client/ID/LWT. | One publish path (`LABVIEW_BRIDGE.md`); two would fight the singleton. |
| **Topic** | Publish to the **single** topic `tmf/<station>/diag` with `subsystem` **in the payload**. | The core consumers (`logs`, `runs`) subscribe the exact `diag` topic; the Debug Server subscribes `diag` + `diag/#`. Single-topic keeps **all three** working. See §3.1. |
| **Wire shape** | The exact `DiagnosticEvent` from `LOGGING.md` §2.3 **plus** optional envelope `trace` (`DEBUG_SERVER.md` §4). | Byte-identical to what Python emits and the Health corpus ingests — zero translation. |
| **Gating** | `Enable Debugging` flag. False ⇒ `Emit` is a near-no-op (early return before any formatting/queueing). | Zero wire cost in production. |
| **Blocking** | Non-blocking at the call site. `Emit` hands off to the Bridge and returns; never waits on the network. | Safe to call from UI / driver / sequencer loops. |
| **Compatibility** | Fields may be **added**, never **removed**. | Preserves the `LOGGING.md` contract. |

This library is **dev-and-prod safe**: it ships in every module, but does nothing
measurable when `Enable Debugging` is off.

---

## 1. What it is

A set of VIs you *call* — not a background task, not a parallel loop, not a second
MQTT connection. Each call takes a structured event, stamps it, serialises it to
the `DiagnosticEvent` JSON, and hands it to the Bridge to publish. That is the
whole job.

It unifies "logging" and "debug-sniff": there is no separate debug client. A diag
emit *is* the debug signal the Debug Server correlates on its timeline.

---

## 2. Where it lives & how it's organised

```
labview/Source/Shared/Diag Emit.lvlib            ← the library (reusable across modules)
    Public/
        Diag Emit.vi
        Diag Emit Exception.vi
        Diag Timed (Open).vi
        Diag Timed (Close).vi
        Diag Set Trace.vi
        Diag Clear Trace.vi
        Diag Configure.vi                         ← one-time init (station, version, enable)
    Private/
        Build DiagnosticEvent (JSON).vi           ← assembles the JSON (JSONtext)
        Format Error Cluster.vi                   ← error cluster → exception object
        Now (epoch seconds, hi-res).vi
    FGV/
        Diag Config (FGV).vi                      ← Enable Debugging, station, source_version
        Diag Seq (FGV).vi                         ← per-process monotonic seq
        Diag Trace (FGV).vi                       ← current run trace string
```

`Diag Emit.lvlib` depends on the **MQTT Bridge** library (for the publish handoff)
and a JSON library (JSONtext recommended). It does **not** depend on any business
module — every DQMH module may use it.

---

## 3. The wire contract

### 3.1 Topic

```
tmf/<station>/diag          QoS 1, retain = false
```

- **Single level**, not `diag/<subsystem>`. The `subsystem` travels in the
  payload. Rationale: the Python core (`logs`, `runs`) subscribes `diag` exactly;
  the Debug Server subscribes `diag` **and** `diag/#`. Publishing to the single
  `diag` topic is captured by everyone. (If the core relays later move to
  `diag/#`, this library can switch to `tmf/<station>/diag/<subsystem>` with no
  payload change — but until then, use the single topic.)
- `<station>` is the station id from config (e.g. `st1`), the same value the Bridge
  scopes all topics with (`LABVIEW_BRIDGE.md` §3).

### 3.2 Payload — `DiagnosticEvent` (LOGGING.md §2.3 + trace)

```json
{
  "seq": 8841,
  "ts": 1748513761.234,
  "level": "info",
  "subsystem": "daq",
  "message": "connect ok",
  "context": { "resource": "Dev1", "simulated": true, "elapsed_ms": 12.4 },
  "exception": null,
  "station": "st1",
  "source_version": "labview/1.4.0",
  "trace": "run:7f3a-0091"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `seq` | integer | yes | per-process **monotonic**, from `Diag Seq (FGV)`. Resets per launch. |
| `ts` | number | yes | UTC **epoch seconds**, high-resolution (fractional). Not a LabVIEW timestamp; not a string. |
| `level` | string | yes | one of `debug` `info` `warning` `error` `critical`. |
| `subsystem` | string | yes | lowercase, short, **dotless** (`daq`, `sequencer`). §6. |
| `message` | string | yes | short, **stable** across versions; IDs go in `context`, not here. |
| `context` | object | yes (`{}` if none) | free-form key→value. |
| `exception` | object \| null | yes | `null` unless an error; shape in §4.3. |
| `station` | string | yes | from `Diag Config (FGV)`. |
| `source_version` | string | yes | from `Diag Config (FGV)` (e.g. build/module version). |
| `trace` | string | **optional** | `"<kind>:<id>"`; **omit the field entirely** when empty (do not send `""`/null). §5. |

The Python validator (`debug_server/analysis.py`) requires `ts, level, subsystem,
message` and a valid `level`; a payload missing any of those is flagged red on the
Debug Server timeline (`DEBUG_SERVER.md` §5.5). Treat that flag as a build error in
the emitter.

---

## 4. Public VI surface

VI names are indicative; match repo conventions. All public VIs are **error-cluster
through** (error in → error out) and **never** make the caller wait on the network.

### 4.1 `Diag Configure.vi` (one-time init)

```
Inputs:  enable_debugging (bool), station (string), source_version (string)
Behaviour:
    store all three in Diag Config (FGV)
    reset Diag Seq (FGV) to 0
Call once at module/launcher init, after the Bridge singleton is up.
```

`Enable Debugging` is read from per-station config at module init
(`DEBUG_SERVER.md` §12.4). When it is false, every `Emit` short-circuits.

### 4.2 `Diag Emit.vi` (the discrete event)

```
Inputs:
    level       enum   { debug, info, warning, error, critical }
    subsystem   string  (lowercase, dotless)
    message     string  (short, stable)
    context     variant / JSON  (free-form key→value; resource, elapsed_ms, …)
    trace       string  optional ("run:7f3a-0091"); empty = omit the field
    error in
Behaviour:
    if not Diag Config.Enable Debugging:  return immediately (error passthrough)
    seq  ← Diag Seq (FGV) ++           (atomic increment)
    ts   ← Now (epoch seconds, hi-res)
    if trace empty:  trace ← Diag Trace (FGV)   (fall back to the current run trace)
    json ← Build DiagnosticEvent (seq, ts, level, subsystem, message,
                                   context, exception=null, station, source_version, trace)
    hand json to MQTT Bridge → publish  topic="tmf/<station>/diag"  qos=1  retain=false
    return (do NOT wait for publish)
Outputs: error out
```

The publish handoff MUST be the Bridge's **non-blocking enqueue** (a DQMH request
to the Bridge, or its internal helper-loop queue) — never a synchronous network
write on the caller's wire. See §7.

### 4.3 `Diag Emit Exception.vi`

```
Inputs: subsystem, message, error cluster (LabVIEW), context, trace, error in
Behaviour:
    as Diag Emit.vi with level = "error"
    exception ← Format Error Cluster.vi(error cluster):
        { "type": "<error name or 'LabVIEWError'>",
          "message": "<error cluster source string>",
          "code": <error code>,
          "call_chain": "<VI call chain, newline-joined>" }
    (NOTE: schema field is "exception"; map code/source/chain into it.)
Outputs: error out  (passes the INCOMING error through unchanged — this VI reports,
                     it does not clear the error)
```

`exception` is `null` for non-error events; an object for errors. Keep the
sub-keys structured (`type`, `message`, `code`, `call_chain`) so the Debug Server /
Health signature matching can key on them later.

### 4.4 `Diag Timed (Open).vi` / `Diag Timed (Close).vi` — the span pattern

Brackets a call to record latency, mirroring Python `diagnostics.timed(...)`
(`LOGGING.md` §2.4).

```
Diag Timed (Open).vi
    Inputs:  subsystem, message (the span name), trace, error in
    Behaviour:
        capture hi-res start tick into a "span" cluster (returned as output)
        emit Diag Emit(level=info, message="<name> start", subsystem, trace)
    Outputs: span (cluster: {name, start_tick, subsystem, trace}), error out

Diag Timed (Close).vi
    Inputs:  span (from Open), context (extra keys), error in
    Behaviour:
        elapsed_ms ← (now - span.start_tick) in ms
        merge elapsed_ms into context
        if error in is good:
            emit Diag Emit(level=info, message="<name> end", context+{elapsed_ms}, trace)
        else:
            emit Diag Emit Exception(message="<name> failed", error cluster,
                                     context+{elapsed_ms}, trace)
    Outputs: error out  (passes the incoming error through)
```

Use around a driver call or a sequencer step. The two emits share `trace`, so the
Debug Server shows the span as start→end on the trace waterfall.

### 4.5 `Diag Set Trace.vi` / `Diag Clear Trace.vi`

```
Diag Set Trace.vi   Inputs: run_id (string)
    store  trace = "run:<run_id>"  in Diag Trace (FGV)
    Call at run-start.

Diag Clear Trace.vi
    clear Diag Trace (FGV) to empty
    Call at run-finished / run-aborted.
```

Once set, `Diag Emit.vi` auto-attaches `trace` (when its own `trace` input is
empty), so every emit inside a run is correlated without threading the id through
each call. This is what makes the Debug Server's run-life reconstructor
(`DEBUG_SERVER.md` §5.2) light up across Python **and** LabVIEW.

`trace` grammar (`DEBUG_SERVER.md` §4.2): v1 = `"run:<run_id>"` only. Do not invent
other kinds yet.

---

## 5. Correlation rules (DEBUG_SERVER.md §4)

- `trace` is an **optional envelope field**. **Omit it entirely** when there is no
  run in scope — do not emit `"trace": ""` or `"trace": null`.
- Stamp it from the FGV (set at run-start), or pass it explicitly on the call.
- `value/#` and `status` are **not** correlated (they are bare retained values) —
  this library never touches those topics; it only emits `diag`.

---

## 6. Naming hygiene (LOGGING.md §6)

- `subsystem`: lowercase, short, **dotless** — `daq`, not `DAQ` or `daq.driver`.
- `message`: short and **stable** across versions; put IDs / values in `context`.
- `level`: **error** = operator action needed; **warning** = something off but the
  module continues; **info** = normal milestone; **debug** = verbose dev detail;
  **critical** = the module/station cannot continue.
- Every emit **self-contained**: `context` carries enough to reconstruct the
  situation without reading neighbours.

---

## 7. Threading & the Bridge handoff (non-negotiable)

1. **Do not** open an MQTT connection in this library. Hand the topic+payload to
   the **one** Bridge DQMH module that owns the connection (`LABVIEW_BRIDGE.md`).
2. The handoff is a **non-blocking enqueue**: a DQMH **Request** (or the Bridge's
   internal helper-loop queue). `Emit` returns immediately; the Bridge's helper
   loop performs the actual `publish`.
3. **Never fork the Bridge's Main Data Wire.** No new parallel loop in the module
   for diagnostics.
4. If the Bridge is down / not connected, the enqueue may be dropped silently —
   diagnostics are best-effort and **must never** block or error the caller.
5. QoS 1, retain **false** (diag is a stream of discrete events, not a retained
   latest-value).

Failure policy: a diag emit must **never** propagate an error to the caller's
business logic. `Emit` passes the incoming error through untouched and swallows any
internal serialisation/enqueue failure.

---

## 8. Where it sits in a DQMH module

```
Launcher / module init
    └─ (Bridge singleton already running — LABVIEW_BRIDGE.md)
    └─ Diag Configure.vi  (enable from config, station, source_version)
Run lifecycle
    └─ Diag Set Trace.vi  (run_id)        at run-start
    └─ … emits during the run carry trace automatically …
    └─ Diag Clear Trace.vi                at run-finished / aborted
Message handlers / loops
    └─ Diag Emit.vi at meaningful events
         (state entered, command received, driver call done, error caught)
    └─ Diag Timed (Open/Close).vi around calls you want latency on
```

Do **not** load a separate "debug client" task; do **not** fork the Bridge wire.

---

## 9. Minimal example (pseudo)

```
// init
Diag Configure.vi   enable=<config>  station="st1"  source_version="labview/1.4.0"

// at run start
Diag Set Trace.vi   run_id="7f3a-0091"

// inside the "self_test" state of the DAQ DQMH module
Diag Timed (Open).vi   subsystem="daq"  message="self_test"
    <call the driver self-test sub-VI>          // error wire threads in
Diag Timed (Close).vi  context={}               // emits elapsed_ms or exception

// a discrete event
Diag Emit.vi  level=info  subsystem="daq"  message="connect ok"
              context={ resource:"Dev1", simulated:true }

// at run finish
Diag Clear Trace.vi
```

Produces on `tmf/st1/diag`:

```json
{ "seq": 8841, "ts": 1748513761.234, "level": "info",
  "subsystem": "daq", "message": "connect ok",
  "context": { "resource": "Dev1", "simulated": true },
  "exception": null, "station": "st1", "source_version": "labview/1.4.0",
  "trace": "run:7f3a-0091" }
```

…which the Debug Server timeline shows interleaved with the Python
`event/step-started` that shares `trace: run:7f3a-0091`.

---

## 10. Verification (real bus, no stubs)

1. **Broker + core up**, `Enable Debugging = true`. Start the Debug Server
   (`.\debug.ps1 -NoAuth`).
2. **MQTT Explorer** subscribed to `tmf/st1/diag` — every emit appears as one JSON
   message on the single topic.
3. **Debug Server timeline** (`http://127.0.0.1:8001`): the emit appears in true
   time order; if a required field is missing, it shows **red** (schema violation
   §5.5) — fix the emitter until it is clean.
4. **Trace view**: `Diag Set Trace.vi` at run-start → the run's LabVIEW emits group
   under `run:<run_id>` alongside Python events on the trace waterfall.
5. **Span**: `Diag Timed (Open/Close)` around a driver call → start/end pair with
   `elapsed_ms` in the close event's `context`.
6. **Gating**: set `Enable Debugging = false`, repeat — **no** messages on
   `tmf/st1/diag` (zero wire cost confirmed).
7. **Exception**: force a driver error → one `level:"error"` event with a populated
   `exception` object (code + source + call chain).

---

## 11. Implementation checklist

- [ ] `Diag Emit.lvlib` created under `labview/Source/Shared/`, depends on MQTT
      Bridge + JSON, no business-module dependency.
- [ ] `Diag Config / Seq / Trace` FGVs implemented; `Diag Configure.vi` wired at
      module init.
- [ ] `Diag Emit.vi` early-returns when disabled; stamps `seq`/`ts`; falls back to
      the trace FGV; hands to the Bridge non-blocking.
- [ ] `Diag Emit Exception.vi` formats the error cluster into `exception` and
      passes the incoming error through.
- [ ] `Diag Timed (Open/Close).vi` emit start/end with `elapsed_ms`; close emits an
      exception on incoming error.
- [ ] `Diag Set/Clear Trace.vi` set at run-start / run-finished.
- [ ] Topic = `tmf/<station>/diag`, QoS 1, retain false; payload matches §3.2.
- [ ] Verified on the Debug Server timeline with **zero** schema violations; gating
      confirmed off.

---

## 12. Reconciliation note (for the Python side)

`DEBUG_SERVER.md` §7 wrote the topic as `diag/<subsystem>`; the Python
`BusDiagSink` (`core/services/diagnostics.py`) currently publishes Python diag to
`diag/<subsystem>`, while `logs`/`runs` subscribe the exact `diag` topic and the
Debug Server subscribes both. This spec pins **LabVIEW to the single `diag`
topic** so LabVIEW diag reaches `logs` + `runs` + the Debug Server. If the project
later switches the core diag relays to subscribe `diag/#`, then both Python and
LabVIEW can move to `diag/<subsystem>` with **no payload change** — the `subsystem`
field already carries the routing. Until then: single topic, subsystem in payload.
```

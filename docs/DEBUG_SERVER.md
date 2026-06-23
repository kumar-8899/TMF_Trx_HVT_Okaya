# DEBUG_SERVER.md — The Debug Server & Unified Diag-Emit Library

This document is a **locked design contract**, peer to `PRINCIPLES.md`,
`CORE.md`, `LABVIEW_BRIDGE.md`, and `LOGGING.md`. Build against this doc,
not against memory. Read `PRINCIPLES.md`, `LOGGING.md`, and
`DATA_TRANSFER.md` first; this doc sits on top of all three.

The Debug Server is the **go-to runtime debugging tool** for the framework.
It gives a developer at the bench one correlated, cross-language view of
everything happening on a station's MQTT bus — Python modules, the LabVIEW
controller, diagnostics, and request/reply round-trips — on a single
timeline.

It is **not** the Workers TCP debug-server model. We replace
"clients connect into a TCP server" with "everything is already on the
broker; the debug server is a subscriber." The bus we already have is the
tap.

---

## 0. Locked decisions

These are settled. Re-open only by editing this file.

| Decision | Choice | Rationale |
|---|---|---|
| **Deployment shape** | **Standalone sidecar process**, not a framework module. Shares the core's schema/model library; separate entrypoint, port, and lifecycle. | A debugger must watch the core while the core is broken; it is dev-only and contributes nothing to the running app; it needs an independent lifecycle. See §2. |
| **Capture scope** | **Low-rate topics only**: `event/#`, `diag/#`, `value/#`, `status`, and request/reply topics. **`stream/#` is never captured.** | High-rate streams are MQTT-Explorer / DAQ-viewer territory with latest-wins semantics. A debug tool must be lossless on what it captures; mixing in `stream/#` forces drop-oldest and risks dropping evidence. |
| **Deployment target** | **Station-local.** Connects to the station's loopback Mosquitto broker. One broker, one developer at the bench. | No multi-broker fan-in, no cross-station auth dance, no central-broker volume problem. Fleet-wide is explicitly out of scope for v1. |
| **Relationship to Diagnostics Bus** | **Superset.** The in-process diag bus (`LOGGING.md`) stays as fast local history; a bridge sink mirrors every diag event onto `diag/#`. The debug server is a pure bus subscriber that correlates bus traffic + diagnostics on one timeline. | "Superset" without reaching into any process's memory — it is all MQTT. See §3. |
| **LabVIEW client library** | **Unified with the diag-emit library.** One library inside each DQMH module publishing structured events to `diag/#`, riding the Bridge singleton. There is **no** separate debug-sniff client. | The bus *is* how LabVIEW modules talk; there is nothing extra to sniff that a diag emit would not already cover. Two publish paths would fight the Bridge-singleton principle (`LABVIEW_BRIDGE.md`). See §7. |
| **Correlation** | **Hybrid.** An optional, uniform, **envelope-level** `trace` field on `event/#` and `diag/#` only. v1 populates it where an ID already exists (`run_id`). v2 widens *what populates* it, never *where it lives*. | Lets us ship the run-life reconstructor with zero contract changes, and makes richer causality a clean extension instead of a retrofit. See §4. |
| **Persistence** | **In-memory ring only.** Lossless within the window, disposable across restarts. Export to JSONL on demand. | A bench tool does not need history to survive a restart; zero disk contention with the diag JSONL sink, nothing to clean up. See §6. |

---

## 1. Why this tool exists

To trace a real incident today you read three log files plus uvicorn
console, correlate timestamps by hand, and hope nothing was buffered
(`LOGGING.md` §2.1). MQTT Explorer shows the topic tree but cannot:

- Put a Python `event/run-started`, a LabVIEW `diag` event, and a
  `value/vbus_main` write in one true-time-ordered narrative.
- Pair a bridge `request` with its `reply` and compute round-trip latency.
- Flag a request that never got a reply (the most common "why did it
  hang" bug across the MQTT seam).
- Validate captured messages against their schemas and highlight
  violations.
- Group a whole test run's life by `run_id` into one waterfall.

The Debug Server does all of these. It is the cross-language spine
`PRINCIPLES.md` §6 calls for, made interactive.

**Non-goal:** the Debug Server is never a runtime dependency of any
module. Health runs, logging, and the controller all work with the Debug
Server absent. The integration with Health/Diagnostics (§9) is strictly
one-directional: the Debug Server *produces* records the Health module
*may* ingest, never the reverse.

---

## 2. Why a sidecar, not a module

Recorded for the Claude Code handoff so the decision is not re-litigated.

| Concern | As a framework module | As a standalone sidecar |
|---|---|---|
| Watch the core while it is broken | Dies with the core; gone exactly when most needed | Survives core crashes, half-failed activation, gate rejections — watches from outside |
| Licensing / entitlement | Gated by the license like a product feature (absurd for a debugger) | No entitlement; dev-only, launched on demand |
| What it contributes to the app | Modules contribute routes / handlers / migrations; the debugger contributes nothing | Observer with its own UI + port; contributes nothing, correctly |
| Lifecycle | Lives and dies with the core process | Launch at the bench, kill when done, run on a second machine pointed at the broker |
| Cost on production stations | Always-present attack surface + resource cost on stations that never open it | Not installed / not launched in production |
| `core.auth` access | Direct injection | Validates bearer tokens over HTTP via the core's `/auth/me` (same token store) — small clean cost |

**Shared code, separate process.** The sidecar imports the core's
`schemas/` and the `DiagnosticEvent` model so schema-validation and export
stay byte-identical to what the Health module ingests. It is a separate
*deployable and entrypoint*, not a code fork.

---

## 3. Architecture

```
Station broker (Mosquitto, loopback-bound)  ──  topic tree: tmf/#
   │
   │  event/#     enveloped domain events   { type, ts, trace?, payload }
   │  diag/#      DiagnosticEvent + trace?   ← Python diag MQTT sink
   │                                           ← LabVIEW diag-emit library (§7)
   │  value/#     retained bare values        (observed by time, NOT correlated)
   │  status      retained + LWT              (observed by time, NOT correlated)
   │  <req>/<rep> request / reply round-trips (paired by reply-topic)
   │
   │  stream/#    HIGH-RATE — NOT captured
   ▼
┌───────────────────────────────────────────────────────────────┐
│  DEBUG SERVER  —  standalone Python sidecar                     │
│                                                                 │
│   MQTT subscriber  → ring buffer (in-memory, lossless, bounded) │
│        capture set: event/# diag/# value/# status + req/rep     │
│                                                                 │
│   ├─ Trace grouper       group enveloped msgs by `trace`        │
│   ├─ Req/reply pairer     pair by reply-topic; flag orphans     │
│   ├─ Schema validator     validate vs core schemas; flag fails  │
│   ├─ Liveness tracker     retained status + LWT → online grid   │
│   └─ Exporter             ring → JSONL (RAG-envelope shape)      │
│                                                                 │
│   REST + WS (own port)  →  Debug Server UI (own React app/page) │
│   token check           →  HTTP GET core /auth/me (bearer)      │
└───────────────────────────────────────────────────────────────┘
                              │ export (one-directional)
                              ▼
        Health / Diagnostics module  (ingests captured sessions; §9)
```

The Debug Server never connects to LabVIEW directly and never talks to a
module's internals. Its only inputs are bus messages. Its only outputs are
its own UI and an export file.

---

## 4. Correlation — the `trace` field

### 4.1 Placement

`trace` is an **optional envelope field**, sibling to `type` and `ts`,
present only on enveloped messages (`event/#` and `diag/#`). It is
**body-agnostic**: the Debug Server reads it without any per-message-type
knowledge, which is what keeps it free of a central message registry.

```
{
  "type":  "step-started",
  "ts":    1748513761.234,
  "trace": "run:7f3a-0091",        ← optional; absent when no ID in scope
  "payload": { "run_id": "7f3a-0091", "step_id": "high_line_transfer", ... }
}
```

For `diag/#`, `trace` rides alongside the `DiagnosticEvent` shape from
`LOGGING.md` §2.3 (added, never removed — preserves that contract):

```
{
  "seq": 5123, "ts": 1748513761.234, "level": "info",
  "subsystem": "sequencer", "message": "step entered",
  "context": { "step_id": "high_line_transfer" },
  "exception": null,
  "trace": "run:7f3a-0091"         ← optional envelope add
}
```

### 4.2 The `trace` value grammar

A `trace` value is `"<kind>:<id>"`. v1 defines one kind:

| Kind | Value example | Set by |
|---|---|---|
| `run` | `run:7f3a-0091` | Python when emitting `event/run-*`; LabVIEW diag-emit when a `run_id` is in scope |

v2 may add kinds (`step:`, `req:`) — that widens *what populates* `trace`
without changing the field's location or the grouper's logic.

### 4.3 What is NOT correlated, and why

`value/#` and `status` are **retained bare values** in the Bridge design;
they carry no envelope. Wrapping them to add `trace` would corrupt the
retained-value semantics the frontend depends on (`DATA_TRANSFER.md`).
Therefore:

> **`value/#` and `status` are observable on the timeline by timestamp,
> but correlation applies only to enveloped `event/#` and `diag/#`
> messages.**

The UI still *shows* a `value/vbus_main` write sitting between two trace
events by time; it just does not claim the value belongs to the trace.

### 4.4 v1 trace reconstruction is free

Because `DATA_TRANSFER.md` §4.1 already gives `run_id` to `run-started`,
`step-started`, `step-completed`, `run-finished`, grouping by `trace`
reconstructs the full life of a run — Python and LabVIEW interleaved —
with no new contract.

---

## 5. Features (ranked by debugging value)

### 5.1 Unified timeline (core)

One scrollable, filterable stream where every captured message sits in
true time order regardless of source language. Filters: subsystem, level
(min), topic prefix, station, time window, free-text substring on
`message`. This is the thing MQTT Explorer cannot give — a correlated
cross-language narrative rather than a topic tree.

### 5.2 Trace view — the run-life reconstructor

Select a `trace` (e.g. `run:7f3a-0091`); get every enveloped message that
carried it, collapsed into one waterfall: which step started, what diag
events fired inside it, the bridge round-trip durations, where it failed.
Five seconds instead of twenty minutes hand-correlating files.

### 5.3 Request / reply latency pairing + orphan detection

The bridge does `request`/`reply` over MQTT. The Debug Server pairs each
request with its reply by the reply-topic, computes round-trip latency,
and **flags orphans** — requests with no reply within a timeout. Orphan
detection is the highest-value single feature for "why did it hang" and
is impossible in a plain topic viewer.

### 5.4 Liveness / LWT panel

Surfaces retained `status` + LWT (`CORE.md` §10) as a live grid: every
module + the LabVIEW bridge, online/offline, last-seen, with the LWT flip
visible the instant the controller dies. "Is the controller alive?" is a
glance.

### 5.5 Schema-violation flagging (proactive bug-finding)

Every captured message is validated against the known core schemas
(matched by `type` + `schema_version`). Violations are **highlighted red
on the timeline** with the validation error attached — a malformed payload
from a half-migrated LabVIEW module shows up as a debugging event, not a
silent downstream crash. This turns the debugger from passive observer
into active linter of the live bus.

### 5.6 Capture sessions + export

Start/stop a named capture; the ring buffer holds the last N events
losslessly; export as JSONL. The export uses the **same RAG envelope your
durable stores use** (`PRINCIPLES.md` §5), so a captured session is a
first-class record the Health module can ingest with no translation (§9).

### 5.7 Replay (v2 — flagged, not v1)

Re-publish a captured session into a **dev broker** to reproduce a field
incident on the bench. Powerful, but it touches "can you safely inject
messages onto a bus," so it is gated hard behind a dev-only flag and a
non-production broker, and deferred to v2.

---

## 6. Capture & persistence model

- **Ring buffer, in-memory, bounded** (e.g. 50 000 events; configurable).
  Append-only within the window; oldest evicted when full. Lossless on the
  captured topic set (which is why `stream/#` is excluded — §0).
- **No disk persistence by default.** Restart loses the buffer. To keep a
  session, export to JSONL.
- **A drop counter** is exposed (`/debug/health`) so a developer can see
  if the buffer wrapped during a long capture.
- The ring is **separate from** the diag bus's own JSONL sink
  (`LOGGING.md` §2.8) — the Debug Server never competes with it for disk.

---

## 7. The LabVIEW Diag-Emit Client Library

This **is** the "debug client library" you would otherwise build
separately. It is unified with diagnostics: one library inside each DQMH
module whose entire job is *take a structured event, stamp it, hand it to
the Bridge to publish on `diag/#`*.

### 7.1 Principles it obeys

1. **Rides the Bridge singleton.** It does **not** open its own MQTT
   connection, client ID, or LWT. It hands the event to the one Bridge
   DQMH module that owns the connection (`LABVIEW_BRIDGE.md`). One publish
   path, period.
2. **Gated by `Enable Debugging`.** When the flag is false, `Emit` is a
   near-no-op (early return before any formatting or queueing) so there is
   zero wire cost in production.
3. **Non-blocking at the call site.** `Emit` enqueues to the Bridge's
   internal helper loop and returns. It never waits on the network. Safe
   to call from the UI loop, a driver loop, or the sequencer loop.
4. **Emits the exact `DiagnosticEvent` shape** from `LOGGING.md` §2.3 plus
   the optional envelope `trace` (§4). Adding fields is allowed; removing
   is not.

### 7.2 Public VI surface

The library is a small DQMH-friendly API. VI names are indicative; match
your repo conventions.

```
Diag Emit.vi
    Inputs:
        level       enum   { debug, info, warning, error, critical }
        subsystem   string  lowercase, short, dotless  ("daq", "sequencer")
        message     string  short, stable across versions
        context     variant/JSON   free-form key→value  (resource, elapsed_ms…)
        trace       string  optional  ("run:7f3a-0091"); empty = omit field
    Behaviour:
        if not Enable Debugging: return immediately
        stamp ts (UTC epoch seconds, high-resolution)
        stamp seq (per-process monotonic; from a Functional Global)
        build DiagnosticEvent JSON (JSONtext) + trace if non-empty
        hand to Bridge → publish on  diag/<subsystem>
        never block; never fork the Bridge's Main Data Wire

Diag Emit Exception.vi
    Inputs: subsystem, message, LabVIEW error cluster, context, trace
    Behaviour: as above with level=error and exception = formatted
               error cluster (code + source + call chain) → "exception"

Diag Timed (Open).vi  /  Diag Timed (Close).vi      ← the span pattern
    Open:  records a high-resolution start timestamp; emits a "start"
           diag event (subsystem, message="<name> start", trace)
    Close: computes elapsed_ms; emits an "end" event with elapsed_ms in
           context; on incoming error, emits level=error with
           exception + elapsed_ms (and passes the error through)
    Use to bracket a driver call or a sequencer step exactly like the
    Python  diagnostics.timed(...)  context manager (LOGGING.md §2.4).

Diag Set Trace.vi  /  Diag Clear Trace.vi
    Stores the current run_id in a Functional Global so Emit calls within
    a run automatically attach  trace = "run:<run_id>"  without threading
    it through every call. Set at run-start; Clear at run-finished.
```

### 7.3 Where it sits in a DQMH module

```
Launcher / module init
    └─ (Bridge singleton already running — LABVIEW_BRIDGE.md)
    └─ read Enable Debugging flag (config)
Module message handlers / loops
    └─ Diag Emit.vi at meaningful events
         (state entered, command received, driver call done, error caught)
    └─ Diag Timed (Open/Close).vi around the calls you want latency on
```

Do **not** load a separate "debug client" background task and do **not**
fork the Bridge's data wire. The library is just VIs you call; the
transport is the Bridge you already have.

### 7.4 Naming hygiene (carried from `LOGGING.md` §6)

- `subsystem` lowercase, short, dotless: `daq`, not `DAQ` or `daq.driver`.
- `message` short and stable; put IDs in `context`, not in the message.
- `level`: **error** = operator action needed; **warning** = something
  off, module continues fine.
- Every emit self-contained: `context` carries enough to reconstruct the
  situation without grepping neighbours.

### 7.5 Minimal LabVIEW emit example (pseudo)

```
// inside the "self_test" state of the DAQ DQMH module
Diag Timed (Open).vi   subsystem="daq"  message="self_test"  trace=<fg run>
    <call the driver self-test sub-VI>
Diag Timed (Close).vi  <error in>   → emits elapsed_ms or exception

// a discrete event
Diag Emit.vi  level=info  subsystem="daq"
              message="connect ok"
              context={ resource:"Dev1", simulated:true, elapsed_ms:12.4 }
              trace=<fg run>
```

This produces, on `diag/daq`:

```json
{ "seq": 8841, "ts": 1748513761.234, "level": "info",
  "subsystem": "daq", "message": "connect ok",
  "context": { "resource": "Dev1", "simulated": true, "elapsed_ms": 12.4 },
  "exception": null, "trace": "run:7f3a-0091" }
```

…which the Debug Server timeline shows interleaved with the Python
`event/step-started` that shares `trace: run:7f3a-0091`.

---

## 8. Debug Server interfaces (its own surface)

The Debug Server exposes its **own** REST + WS on its **own** port — it is
not mounted under the core's web shell. Shapes follow `DATA_TRANSFER.md`
conventions (RFC-7807 errors, enums as strings, lists always present,
optional fields absent/null).

```
REST
GET  /debug/events
        ?since=<seq|ts> &level=warning &subsystem=daq
        &topic=event/ &trace=run:7f3a-0091 &limit=500
     → list of captured records, newest last

GET  /debug/traces
     → [ { trace, first_ts, last_ts, count, has_error } ]   # discovered traces

GET  /debug/trace/{trace}
     → ordered waterfall of all enveloped messages for that trace

GET  /debug/requests
        ?status=orphan|paired &since=
     → [ { req_topic, reply_topic, sent_ts, reply_ts|null,
           latency_ms|null, status } ]                       # §5.3

GET  /debug/liveness
     → [ { client, status, last_seen, lwt_fired } ]          # §5.4

GET  /debug/violations
     → [ { ts, topic, type, schema_version, error } ]        # §5.5

GET  /debug/health
     → { buffer_used, buffer_capacity, dropped, subscribers, broker_connected }

POST /debug/capture/start   { name }      → 200 { capture_id }
POST /debug/capture/stop    { capture_id} → 200 { event_count }
GET  /debug/capture/{id}/export           → JSONL (RAG-envelope shape; §9)

WS
WS   /debug/stream
        ?token=<bearer> &level=info &subsystem=daq &topic=event/
     → one captured record per emission (live tail), same filters as REST
```

Auth: bearer token validated by calling the core's `GET /auth/me`
(`DATA_TRANSFER.md` §1). Viewer role for read; the capture/export and any
future replay endpoints require a higher role and a dev-only flag.

---

## 9. Integration with the Health / Diagnostics module

Three concrete hooks, all respecting append-only, RAG-ready,
structured-key principles. **One-directional only** (§1 non-goal).

### 9.1 Zero-translation ingestion

Because the Debug Server captures the **same `DiagnosticEvent` shape** the
Health Check module already persists, a capture export (`/debug/capture/
{id}/export`) drops straight into the health corpus with no mapping layer.
A field developer's debug capture becomes a health-run record.

### 9.2 Signature feed

The Health module does structured-key signature matching for
auto-suggestion. The Debug Server's two derived signals are themselves
clean structured keys:

- **Schema violations** (§5.5): `{ type, schema_version, error_kind }`.
- **Orphaned requests** (§5.3): `{ req_topic, timeout_ms }`.

Both can emit into whatever signature taxonomy Health settles on. **This
is a reason to close the open Health Check decision about whether the
signature taxonomy reuses the logs/error module's taxonomy** — the Debug
Server is another *producer* into that taxonomy, so the choice now has
more than one dependent.

### 9.3 Diagnostic bundle artifact

`BORROWABLE_MODULES.md` #3 specs a `/diagnostics/bundle` ZIP. A Debug
Server capture export becomes one more artifact in that bundle, so
"export diagnostics, email engineer" now includes the correlated
cross-language timeline, not just three flat log files.

### 9.4 The boundary (what we deliberately do NOT do)

- The Health module **never depends on the Debug Server at runtime.**
- The Debug Server **never writes** to the health corpus directly — it
  produces an export; the Health module chooses to ingest it.
- The Debug Server is **not** in the activation gate, not licensed, not in
  `/modules/status`.

This keeps "no god-modules, standalone-runnable" intact.

---

## 10. Required contract for re-implementation

A re-host (or a future fleet-wide variant) that keeps this contract MUST:

1. Subscribe to `event/#`, `diag/#`, `value/#`, `status`, and the
   request/reply topics; **never** subscribe to `stream/#`.
2. Hold a bounded, lossless, in-memory ring of captured records; expose a
   drop counter.
3. Group enveloped messages by the optional envelope `trace` field;
   leave `value/#` / `status` time-ordered but uncorrelated.
4. Pair requests with replies by reply-topic; flag orphans on timeout.
5. Validate captured messages against the core schemas by
   `type` + `schema_version`; surface violations.
6. Track retained `status` + LWT as a liveness grid.
7. Export captures in the RAG envelope shape so Health can ingest them.
8. Run as its own process with its own REST + WS surface; validate tokens
   against the core's auth; never become a runtime dependency of any
   module.

LabVIEW-side, the only obligation is §7: the unified diag-emit library
publishing the `DiagnosticEvent` + `trace` shape on `diag/#` via the
Bridge singleton, gated by `Enable Debugging`.

---

## 11. Implementation phases

| Phase | Scope | Output |
|---|---|---|
| **DS1** | Sidecar skeleton: MQTT subscribe (capture topic set), ring buffer, `/debug/events` + `/debug/health`, token check via core `/auth/me`. | subscriber + ring + 2 endpoints |
| **DS2** | WS live tail `/debug/stream` with filters; the unified timeline UI (filter bar + virtualized table + expand-context). | live tail + first UI |
| **DS3** | Trace grouper + `/debug/traces` + `/debug/trace/{id}`; trace-view UI (waterfall). Depends on `trace` being emitted (§4). | run-life reconstructor |
| **DS4** | Request/reply pairer + orphan detection (`/debug/requests`); liveness panel (`/debug/liveness`). | the two "why did it hang / is it alive" features |
| **DS5** | Schema validator against core schemas (`/debug/violations`); red flagging on timeline. | proactive bus linter |
| **DS6** | Capture sessions + JSONL export in RAG envelope; bundle hook for Health. | Health integration (§9) |
| **DS7** (v2) | Replay into a dev broker (gated, non-prod). | incident reproduction |

LabVIEW diag-emit library (§7) is a parallel track, prerequisite for DS3's
LabVIEW-side traces but independently useful from day one (it feeds the
diag bus regardless of the Debug Server).

---

## 12. Open decisions to close before DS1

1. **`trace` value grammar ownership.** Confirm `"run:<run_id>"` as the v1
   form and who stamps it on the Python side (the small module that
   subscribes to `event/run-*` and persists run records, per `CORE.md`
   §7, is the natural owner).
2. **Request/reply topic convention.** The orphan detector needs to know
   how a request names its reply topic. Confirm the bridge's
   reply-topic scheme (`LABVIEW_BRIDGE.md`) so the pairer can match
   without per-call configuration.
3. **Health signature taxonomy.** Settle the open Health Check decision
   (reuse logs/error taxonomy vs. own) — the Debug Server is now a second
   producer into it (§9.2).
4. **Debug Server port + `Enable Debugging` config home.** Pick the
   sidecar's default port and where the LabVIEW `Enable Debugging` flag
   lives (per-station config, read at module init).

---

## 13. Implementation status (this build)

**Built: DS1–DS6** (backend sidecar + lean self-served UI). **DS7 (replay) deferred** to v2 per §5.7.

Package `backend/debug_server/` (separate process, port **8001**):
- `subscriber.py` — aiomqtt capture of `event/#`, `diag` + `diag/#`, `value/#`,
  `status`, `cmd/#` (requests + `cmd/resp/#` replies). **`stream/#` never subscribed** (§0).
- `capture.py` — `parse`/classify + bounded lossless `Ring` with a drop counter (§6).
- `analysis.py` — `validate` (§5.5), `Pairer` + orphan detection (§5.3),
  `group_traces` (§5.2), `Liveness` from retained status/LWT (§5.4).
- `ingest.py` — pipeline + WS fan-out + capture sessions + JSONL export in the
  RAG envelope shape (§5.6 / §9.1).
- `app.py` — REST + WS per §8; token check via core `/auth/me` (`auth.py`);
  serves the UI at `/`.
- Entry: `python run_debug_server.py` (env: `TMF_DEBUG_PORT`, `TMF_BROKER_HOST/PORT`,
  `TMF_CORE_URL`, `TMF_STATION`, `TMF_DEBUG_NO_AUTH=1` for dev).

Core touch (only): `BusDiagSink` (`core/services/diagnostics.py`) mirrors Python
diag onto `diag/<subsystem>` via the Bridge when the bridge is up (§0/§3) — so the
timeline carries Python diagnostics, not just LabVIEW's.

Deviations / notes vs the contract:
- **Topics** use this repo's `tmf/{station}/…` scoping; replies are `cmd/resp/<client>`
  paired with `cmd/<op>` by the payload `id` (the bridge's reply scheme, §12.2).
- **`trace` is read-only in v1.** Producers are the LabVIEW diag-emit library (§7,
  LabVIEW track — not built here) and any Python event already carrying `trace`.
  The grouper needs no contract change to light up once producers stamp it.
- **Schema validation** is presence/shape based (the core ships no per-message-type
  schemas yet); extend `analysis.validate` as typed schemas land.
- The LabVIEW **diag-emit library (§7)** is the separate LabVIEW track; the Python
  side is ready to capture what it publishes.

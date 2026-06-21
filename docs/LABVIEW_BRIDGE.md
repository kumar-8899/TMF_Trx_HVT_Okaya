# LABVIEW_BRIDGE.md — LabVIEW ↔ Python Wire Contract (MQTT)

This is the **LabVIEW ↔ Python** contract. It is the sibling of
`DATA_TRANSFER.md`, which is the **Python ↔ frontend** contract. The frontend
never sees this layer; it talks only to Python.

Payloads here deliberately mirror `DATA_TRANSFER.md` so Python relays them to
the browser with almost no transformation.

---

## 1. Topology & locked decisions

- **LabVIEW does not face the browser. Python is the only web edge.** Without LabVIEW Web Services, hand-rolling a browser-facing WebSocket is fragile; Python already owns auth, CORS, RFC-7807, and the four WS endpoints. One web edge keeps the frontend unchanged and auth in one place.
- **LabVIEW is the controller (Option A):** it owns test execution — sequence, step timing, abort/timeout, safety. Python hosts the business modules and the web edge (`CORE.md`).
- **Transport: MQTT.** Chosen over ZeroMQ and Web Services for the multi-station roadmap — retained last-value, Last-Will liveness, QoS, topic wildcards, broad library support, and dashboard/cloud interop.
- **Serialization: JSON** (JSONtext on the LabVIEW side; matches recipes and the frontend wire).

```
   Browser (React) ── DATA_TRANSFER.md, UNCHANGED (REST + WS, bearer auth, CORS)
         │
         ▼
  ┌──────────────────────────────┐
  │ Python backend (the platform)│  auth · web · db · modules · bridge client
  └────────┬─────────────────────┘
           │  MQTT  (local broker, loopback)
  ┌────────┴─────────────────────┐
  │ LabVIEW (DQMH controller)    │
  │  ONE Bridge module ── MQTT   │
  │   ▲ DQMH broadcasts / requests
  │  controller · DAQ · safety · drivers (HAL) …
  └──────────────────────────────┘
```

---

## 2. Broker & deployment

- **One local broker per station.** Co-located LabVIEW + Python (+ frontend) connect to it on loopback.
- **Multi-station:** each local broker **bridges** selected low-rate topics up to a **central broker** for the fleet dashboard — `event/#`, `status`, `value/#`. **Do NOT bridge `stream/#`** (never put kHz firehoses on the uplink).
- **Singleton:** local broker only, no bridge, no central.
- **Broker choice:** Mosquitto for the local broker and small fleets; EMQX (clustered) for large fleets.

```
  Station 1                         Station 2
  LabVIEW ┐                         LabVIEW ┐
  Python  ├─ local broker           Python  ├─ local broker
  browser ┘   (127.0.0.1)           browser ┘   (127.0.0.1)
                 │                       │
                 └──────── bridge ───────┘   (event/#, status, value/# — NOT stream/#)
                              │
                              ▼
                       Central broker ──── Fleet dashboard (read-only: tmf/+/…)
```

**Security.** The local broker binds `127.0.0.1`, so only local processes reach
it — the same trust boundary as the OS; no client auth is required, and the
frontend never connects to the broker. The **central bridge connection crosses
the network**, so it MUST be authenticated (broker credentials) and SHOULD be
TLS; the dashboard connects to the central broker read-only with its own
credentials. All web authentication stays at the Python edge
(`DATA_TRANSFER.md` §1). If LabVIEW runs on a separate target *within* the
station (e.g. a real-time controller), bind the local broker to the station's
private interface with broker auth instead of loopback.

---

## 3. Topic tree

`tmf/{station}/…` — `{station}` is e.g. `st1`; singleton uses one value.

| Topic — `tmf/{station}/…` | Dir | QoS | Retained | Carries |
|---|---|---|---|---|
| `cmd/{op}` | Py→LV | 1 | — | command; reply via payload `reply_to`+`id` (§5) |
| `query/{op}` | LV→Py | 1 | — | LabVIEW-initiated request to a **Python-served** handler; reply via payload `reply_to`+`id` (§5). E.g. `recipe.fetch` at run start. |
| `stream/{signal}` | LV→Py | 0 | — | high-rate frame (`DATA_TRANSFER.md` §3.3); Python keeps latest |
| `value/{variable}` | LV→Py | 1 | **yes** | last-known scaled value `{value, ts}` (§3.3 / §5.4) |
| `event/{kind}` | LV→Py | 1 | — | domain event envelope (§3.2): run / step / safety |
| `diag` | LV→Py | 1 | — | diagnostics (`LOGGING.md` §2.3) |
| `status` | LV→Py | 1 | **yes** | online / offline; registered as the **LWT** |

The central dashboard subscribes `tmf/+/event/#`, `tmf/+/status`,
`tmf/+/value/#`. It never subscribes `stream/#`.

`{signal}` is `ai`, `di`, and later `var.<name>`. `{kind}` is the event type
(`run-started`, `step-completed`, `run-finished`, `safety-trip`, …).

---

## 4. Message envelopes

All JSON, obeying the stability rules in §11. Each mirrors a shape Python
already forwards to the frontend.

**Command** (Py → LV, `cmd/{op}`):
```json
{ "id": "c7f1…", "op": "hello.echo", "args": { "msg": "hi" },
  "reply_to": "tmf/st1/cmd/resp/<python-client>" }
```
`reply_to` and `id` are carried **in the payload** so a 3.1.1 responder needs no
MQTT-5 features (see §5).

**Reply** (LV → Py, to `reply_to`, carrying the same `id`):
```json
{ "id": "c7f1…", "ok": true,  "result": { "echoed": { "msg": "hi" }, "station": "st1", "ts": 1748513761.234 } }
{ "id": "c7f1…", "ok": false, "error":  { "code": "daq_not_connected",
                                          "message": "AI task not running",
                                          "detail": "start the stream first" } }
```

**Stream frame** (LV → Py, `stream/{signal}` — `DATA_TRANSFER.md` §3.3):
```json
{ "t": 1748513761.234, "seq": 1024, "values": { "ai0": 5.001, "ai1": 3.300 } }
```

**Value** (LV → Py, `value/{variable}`, retained — §5.4):
```json
{ "value": 264.0, "ts": 1748513761.234 }
```

**Event** (LV → Py, `event/{kind}` — §3.2 envelope):
```json
{ "type": "step-completed", "ts": 1748513761.234,
  "payload": { "step_id": "high_line_transfer", "status": "PASSED", "elapsed_ms": 832.4,
               "measurements": [ { "name": "vbus_main", "value": 264.0, "units": "V" } ] } }
```

**Diagnostic** (LV → Py, `diag` — `LOGGING.md` §2.3):
```json
{ "seq": 5, "ts": 1748513761.234, "level": "warning", "subsystem": "daq",
  "message": "producer error", "context": { "resource": "Dev1" }, "exception": null }
```

**Status** (LV → Py, `status`, retained):
```json
{ "state": "online", "ts": 1748513761.234, "uptime_s": 1234, "publishes": 10293, "cmd_pending": 0 }
```
The **LWT** payload is fixed at connect time and is `{ "state": "offline" }`;
Python uses receipt time, not a payload timestamp, for the offline transition.

---

## 5. Commands (request / reply)

- **Envelope:** `cmd {id, op, args, reply_to}` → `reply {id, ok, result}` or `{id, ok:false, error:{code, message, detail}}`.
- **Transport — primary (MQTT 3.1.1-safe).** The LabVIEW MQTT library speaks
  **3.1.1**, so the contract MUST NOT rely on MQTT-5 features. Python publishes to
  `cmd/{op}` with `reply_to` (a fixed per-client reply topic, e.g.
  `tmf/{station}/cmd/resp/{client}`) and `id` **in the JSON payload**. The Bridge
  reads `reply_to` + `id` from the payload and publishes the reply to that topic
  carrying the same `id`. Python is subscribed to its reply topic and matches on
  `id`. This is the only mechanism a responder must implement.
- **Transport — optional optimization (MQTT 5).** Python (a V5 client) also sets
  `Response-Topic` + `Correlation-Data` on the publish; a V5 responder may use
  them instead. Mosquitto strips these for a 3.1.1 subscriber, which is why the
  payload-carried fields above are authoritative. Never depend on V5-only props
  across the seam.
- **Direction.** `cmd/{op}` is **Py→LV** (LabVIEW serves; e.g. `daq.*`, `run.*`).
  `query/{op}` is **LV→Py** (Python serves; e.g. `recipe.fetch`). Same envelope
  and reply mechanism both ways; separate topic classes so the two never collide.
  Python: `bridge.serve(op, handler)` answers a `query/{op}`; `bridge.request`/
  `bridge.query` issue a `cmd`/`query`. LabVIEW reads a recipe at run start by
  publishing `query/recipe.fetch {recipe_id, version, station, run_parameters}`
  and reading the substituted recipe JSON from the reply.
- **Naming:** `{domain}.{action}`, dotted. Phase-0: `hello.echo`. Foreshadowed as modules land: `daq.ai.read`, `daq.ai.stream.start` / `stop`, `daq.di.read`, `variable.read`, `variable.write`, `run.start`, `run.abort`. The full catalogue is documented per controller/module as built.
- **Errors → RFC 7807 in Python.** The Bridge returns a structured `error`; Python maps `code` → `type`/`title` and `message`/`detail` → the ProblemDetail body (`DATA_TRANSFER.md` §2.2). A `bridge.request` timeout maps to **502** (the doc's "driver / external dependency").

### 5.1 Phase-1 command catalogue (pinned)

All replies use `{id, ok, result}` or `{id, ok:false, error:{code,message,detail}}`.
LabVIEW reads `reply_to` + `id` from each command payload (§5).

| op | args | result on ok |
|---|---|---|
| `daq.ai.stream.start` / `daq.di.stream.start` | `{ rate?, channels? }` | `{ started: true }` |
| `daq.ai.stream.stop` / `daq.di.stream.stop` | `{}` | `{ started: false }` |
| `daq.ai.read` / `daq.di.read` | `{ channels? }` | `{ values: { ai0: … } }` |
| `variable.read` | `{ name }` | `{ value, ts }` |
| `variable.write` | `{ name, value }` | `{ written: true }` |
| `run.start` | `{ run_id, recipe_id, version?, run_parameters? }` | `{ started: true }` |
| `run.abort` | `{}` | `{ aborted: true }` |
| `health.check.<id>` | `{ instance_id?, … }` | `CheckVerdict` `{ status, summary, data, error? }` |

`health.check.<id>`: the Health module dispatches `bridge`/`hardware` checks that
have no Python executor to a LabVIEW handler (HEALTH_CHECK.md §12). The handler
runs the check, times it, and replies with a verdict whose `status` is one of
`pass | fail | timeout | error` (the module fills `unavailable`/`timeout` itself
when no handler answers). E.g. `health.check.bridge.queue_depth → {status:"pass",
summary:"queue ok", data:{depth:2}}`. Connectivity checks `bridge.online` /
`bridge.roundtrip` / `bridge.clock_skew` are computed Python-side (the last reuses
`hello.echo`'s `ts`) and need **no** new handler.

`run.start`: **Python mints `run_id`** and resolves `recipe_id` (directly or from
a scanned barcode). LabVIEW reads the recipe by publishing
`query/recipe.fetch { recipe_id, version, run_parameters }` and running the
returned (substituted) JSON.

Controller events (LV → Py, `event/{kind}`, envelope `{type, ts, payload}`) the
`runs` module persists: `run-started` `{run_id, recipe_id}`, `step-started` /
`step-completed` `{run_id, step_id, status, …}`, `test-result`
`{run_id, serial_no?, test_name, expected, measured, result, cycle_time_ms}`,
`run-finished` `{run_id, result}` (`result` = PASS|FAIL|ABORTED), `run-aborted`
`{run_id, reason}`, `safety-trip` `{reason}`. `run_id` is required for a record to
join the current-state run.

---

## 6. Streaming & last-value

**Streaming.** A `…stream.start` command tells LabVIEW to begin producing; the
producer publishes one frame per tick on `stream/{signal}` at **QoS 0, not
retained**. Python keeps only the latest frame per topic; loss under load is
expected and correct (latest-wins, `DATA_TRANSFER.md` §3.5). A `…stream.stop`
command ends production. The browser WS endpoints still gate on "is the stream
running."

**Last-value.** LabVIEW publishes each variable's current scaled (engineering-
unit) value **retained** to `value/{variable}`. Any new subscriber — a
reconnecting Python, the dashboard, a freshly opened browser via Python — gets
it instantly, which is snapshot-on-join (§3.3) and `GET /variables/{name}/value`
(§5.4) for free. If no retained value exists yet, Python falls back to a
`variable.read` command.

**Escalation past 1 kHz.** First lever: **batch** N samples per stream message
(`DATA_TRANSFER.md` §7). Second: binary-encode the `values` block inside the
JSON envelope. Never split the transport.

---

## 7. Liveness

- **Last Will & Testament.** The Bridge registers its will as `status = {"state":"offline"}` retained on connect, then publishes `{"state":"online", …}` retained once connected. An ungraceful death makes the broker auto-publish offline.
- **MQTT keepalive.** A hung-but-connected client lets its keepalive (PINGREQ) lapse, so the broker fires the LWT — keepalive + LWT covers crashes *and* hangs.
- **Periodic status republish** (e.g. every 5 s) carries health: uptime, publish counters, pending-command depth. Liveness comes from the LWT; health detail from the periodic status.
- Python `/readyz` is ready only when the retained `status` is `online` (`CORE.md` §5).

---

## 8. The DQMH side

- **One Bridge module owns the MQTT connection and every topic.** Internal modules stay pure DQMH and never touch MQTT.
- **DQMH Broadcast (User Event, 1→N) ≡ MQTT PUB.** Producers — the DAQ acquisition module, the controller, safety — broadcast; the Bridge is registered for those broadcasts and publishes each to the right topic.
- **DQMH Request-and-Wait-for-Reply ≡ MQTT cmd/reply.** The Bridge receives on `cmd/+`, issues the matching DQMH request to the owning module, waits, and publishes the reply with the same correlation data.
- **Connect sequence:** set LWT → connect → publish `status = online` (retained) → subscribe `cmd/+` → start the periodic-status timer.
- **One Bridge handles all streams.** Four AI at 1 kHz plus five DI is ≈ 2000 small publishes/sec — comfortable for one MQTT client and for Mosquitto. Escalation is internal (batching, or a dedicated publish loop / cloned helper inside the Bridge), never more Bridge modules.
- **Swap the transport later → only the Bridge changes;** internal modules don't.

---

## 9. The Python side

- The core's `bridge` service (`CORE.md` §1 / CoreServices) is an MQTT client exposing `publish(topic, payload, qos, retain)`, `request(op, args, timeout) → reply`, `subscribe(topic, handler)`, plus `station` and the link status.
- **Relay is near pass-through.** Python subscribes to the broker, applies its existing latest-frame cache (streams) and event fan-out / diagnostics bus (events, diag), and forwards to the existing frontend WS endpoints unchanged:

| Bridge topic | Frontend WS endpoint (`DATA_TRANSFER.md` §4) |
|---|---|
| `stream/ai` | `/instruments/daq/ai/stream/ws` |
| `stream/di` | `/instruments/daq/di/stream/ws` |
| `event/*` | `/ws/station` |
| `diag` | `/diagnostics/stream` |

---

## 10. Multi-station bridging (concrete)

On each station's local broker, configure an outbound bridge to the central
broker that forwards only the low-rate topics, each scoped by station id:

```
# mosquitto.conf (station st1 → central) — conceptual
connection st1-to-central
address    central.broker.example:8883
bridge_cafile  /etc/.../ca.crt          # TLS
remote_username st1
topic tmf/st1/event/#  out 1
topic tmf/st1/status   out 1
topic tmf/st1/value/#  out 1
# tmf/st1/stream/# is intentionally NOT bridged
```

Station ids MUST be unique across the fleet. The dashboard authenticates to the
central broker read-only and subscribes `tmf/+/event/#`, `tmf/+/status`,
`tmf/+/value/#`.

---

## 11. Wire-shape stability rules

Mirrors `DATA_TRANSFER.md` §6:

1. Field names are stable; adding fields is fine, renaming is breaking.
2. Numbers keep their declared form — voltage float, timestamp `epoch seconds, float`.
3. Enums are strings (`level`, `state`, `status`), never integers.
4. Optional fields are explicitly absent or `null`, never empty strings.
5. Lists are always present, even if empty.
6. Errors always use the structured `error` shape, never bare strings.
7. Adding topics is fine; renaming or removing a topic is breaking.

---

## 12. Phase-0 LabVIEW stub (the LabVIEW half of the Hello module)

`CORE.md` §9–§10 reference a LabVIEW stub. This is the minimal Bridge that proves
the whole skeleton end to end:

- Connect to the local broker; set the LWT, publish `status = online` retained, start the periodic-status republish, subscribe `cmd/+`.
- Handle `hello.echo`: reply `{ "echoed": <args>, "station": "...", "ts": ... }` via the response-topic + correlation-data.
- Publish a synthetic `stream/ai` frame at ~10 Hz: `{ "t": …, "seq": <n++>, "values": { "ai0": <sine or counter> } }`.
- Publish a retained `value/vbus_main` = `{ "value": …, "ts": … }`, updated periodically.

This satisfies `CORE.md` §10 criteria **5** (cmd round-trip), **6** (stream +
retained value + diag visible in MQTT Explorer), and **7** (kill the stub → LWT
flips `status` to offline → `/readyz` goes not-ready). The stub is replaced by
the real DAQ and controller modules afterward.

---

## 13. What to copy verbatim / re-implementer contract

A non-LabVIEW controller that wants to keep this contract MUST:

1. Provide one publish path that is safe to call from any thread (the Bridge pattern) onto MQTT.
2. Honour the topic tree (§3), the QoS/retain table, and the envelopes (§4) verbatim — adding fields is fine, removing them is not.
3. Register the LWT on `status` and keep `status` retained; publish `online` on connect.
4. Implement cmd/reply by reading `reply_to` + `id` from the command payload and replying there with the same `id` (the 3.1.1-safe contract, §5). MQTT-5 response-topic/correlation are optional.
5. Keep `stream/#` local; bridge only `event/#`, `status`, and `value/#` to the central broker.

Honour these and the existing Python platform and React frontend work unchanged.

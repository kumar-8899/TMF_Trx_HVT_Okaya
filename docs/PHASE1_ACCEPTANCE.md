# Phase-1 acceptance — DAQ / stream + controller vertical

The first real slice (PRINCIPLES build order step 1). Proves the high-rate
transport, the command path, and the LabVIEW-as-controller run path end to end.

## What was built (Python platform half)
- Core: bridge **latest-frame cache** (`bridge.latest`) + **StreamHub** fan-out.
- `daq` module: ai/di stream start/stop, latest REST, **WS stream relays**
  (gated, snapshot-on-join), variable read/write + retained last-value.
- `runs` module: `run.start/abort`, `event/run-*` → **run records** (CORE.md §7),
  `/runs` queries, **`/ws/station`** + **`/diagnostics/stream`** fan-out.
- Contracts pinned: LABVIEW_BRIDGE.md §5.1 command catalogue, `contracts/daq.md`,
  `contracts/runs.md`.

## Status

| Criterion | Proven by | Status |
|---|---|---|
| Stream control (start/stop) issues commands | `modules/daq/tester` | ✅ |
| `stream/ai|di` frames cached + WS fan-out (gated, snapshot) | `modules/daq/tester` | ✅ |
| Variables: retained value + read/write | `modules/daq/tester` | ✅ |
| `run.start/abort` proxied to controller | `modules/runs/tester` | ✅ |
| `event/run-*` → durable run records | `modules/runs/tester` | ✅ |
| `/ws/station` + `/diagnostics/stream` fan-out | `modules/runs/tester` | ✅ |
| Live vertical against **real LabVIEW** | `tools/check_phase1.py --no-stub` | ⏳ pending real DAQ/controller VIs |

Automated tests use in-test fakes (CI). The live row is the acceptance gate and
needs the real LabVIEW DAQ + controller implementing LABVIEW_BRIDGE.md §5.1.

## Live gate

Broker up + real LabVIEW DAQ/controller running:

```pwsh
cd backend
python -m tools.check_phase1 --no-stub
python -m tools.check_phase1 --no-stub --variable vbus_main --write-var setpoint --write-value 12.5
```

Walks: `daq`/`runs` loaded → bridge online → `ai.stream.start` → frames on
`GET /instruments/daq/ai/latest` → variable read (+ optional write) → `run.start`
→ a row in `GET /runs` → `run.abort`. Watch `tmf/#` in MQTT Explorer alongside.

## LabVIEW to-do (for the live gate to go green)
Implement, in the DQMH Bridge + DAQ/controller modules:
1. `daq.{ai,di}.stream.start/stop` → begin/stop publishing `stream/{signal}` ~kHz.
2. `variable.read` / `variable.write`; publish retained `value/{name}`.
3. `run.start` / `run.abort`; emit `event/run-started`, `step-*`,
   `event/run-finished` (each with `run_id`).
All replies via the payload `reply_to` + `id` (3.1.1-safe, §5).

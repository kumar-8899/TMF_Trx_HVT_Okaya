# Contract — `daq` (DAQ Instruments)

Instruments backed by the LabVIEW controller: analog/digital streaming + reads,
and station variables. One variant: `default`. Entitlement key `daq`.

## Commands issued (Py → LV, LABVIEW_BRIDGE.md §5.1)
`daq.ai.stream.start/stop`, `daq.di.stream.start/stop`, `daq.ai.read`,
`daq.di.read`, `variable.read`, `variable.write`.

## Subscriptions (LV → Py)
`stream/ai`, `stream/di` (cached latest-wins + fanned out), `value/#` (retained
last-value cache).

## HTTP surface
| Method | Path | Behaviour |
|---|---|---|
| POST | `/instruments/daq/{ai,di}/stream/start` | start producing; body = args |
| POST | `/instruments/daq/{ai,di}/stream/stop` | stop producing |
| GET  | `/instruments/daq/{ai,di}/latest` | latest cached frame (404 if none) |
| WS   | `/instruments/daq/{ai,di}/stream/ws` | gates on stream running (close 4409); snapshot-on-join, then live frames |
| WS   | `/instruments/values/ws` | live station variable values: snapshot-on-join (every cached value), then `value/{name}` updates as `{ name, value, ts }` |
| GET  | `/variables/{name}/value` | retained value, else `variable.read` |
| PUT  | `/variables/{name}/value` | body `{value}` → `variable.write` |

## Payload shapes
- Stream frame: `{ t, seq, values: { ai0: … } }` (BRIDGE §4).
- Value: `{ value, ts }` (retained).
- Errors: bridge timeout → 502, not connected → 503, unknown variable → 502.

## Standalone test
`core + daq + stub bridge` — `backend/modules/daq/tester/test_daq.py`
(command + running state, latest proxy, WS gating/snapshot/live, variable
read/write + REST). Live gate: `python -m tools.check_phase1 --no-stub`.

# Contract — `runs` (Runs)

Controller run-control proxy + run-record persistence + station/diag fan-out.
LabVIEW owns execution; this module relays control and turns controller events
into durable records (CORE.md §7). One variant: `default`. Entitlement key `runs`.

## Commands issued (Py → LV)
`run.start` `{recipe?, params?}`, `run.abort` `{}`.

## Subscriptions (LV → Py)
`event/#` (persisted + fanned out), `diag` (fanned out).

## Persistence (CORE.md §7, base Repository)
- Every `run-*` / `step-*` / `safety-*` event → an append-only `run_event` record.
- `run-started` / `run-finished` upsert a current-state `run` record keyed by
  `run_id` (`running` → `finished`, merging `result`). The RAG envelope (id, type,
  ts, station, source_version, summary) is stamped automatically.

## HTTP / WS surface
| Method | Path | Behaviour |
|---|---|---|
| POST | `/runs/start` | body = params → `run.start` |
| POST | `/runs/abort` | `run.abort` |
| GET  | `/runs` | run records (`since`, `limit`) |
| GET  | `/runs/{id}` | one run record (404 if absent) |
| WS   | `/ws/station` | fan-out of all `event/*` envelopes |
| WS   | `/diagnostics/stream` | fan-out of `diag` events |

## Standalone test
`core + runs + stub bridge + :memory: db` —
`backend/modules/runs/tester/test_runs.py` (control commands, lifecycle →
records, non-run ignored, WS fan-out). Live gate:
`python -m tools.check_phase1 --no-stub`.

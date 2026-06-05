# Phase 2 — Logs acceptance (Action & Error Logs)

Second business module (build order step 2). Persistence + history side of the
diagnostics bus. Spec: [contracts/LOGS.md](contracts/LOGS.md) +
[LOGGING_addendum_labview_diag_emit.md](LOGGING_addendum_labview_diag_emit.md).
Reconciled to our live contracts (permission-first, station-relative topics).

## Status

| # (prompt §8) | Criterion | Proven by | Status |
|---|---|---|---|
| 1 | core+logs boots via gate; `/modules/status` shows logs | `tests/test_logs_e2e.py` | ✅ |
| 2 | license `logs:false` → not loaded, reason shown | `tests/test_logs_e2e.py` | ✅ |
| 3 | `diag.warning` anywhere persists as error_log, no call-site change | `modules/logs/tester` + e2e | ✅ |
| 4 | recurring identical error within window → 2 rows not N | `modules/logs/tester` (47×→2) | ✅ |
| 5 | `record_action(...)` persists attributed action_log | `modules/logs/tester` | ✅ |
| 6 | query/stat endpoints correct, paginated, permission-gated, RFC-7807 | `modules/logs/tester` | ✅ |
| 7 | pruning honors max_days + max_records, DB store only | `modules/logs/tester` | ✅ |
| 8 | tester passes with no broker (Python path) | whole `modules/logs/tester` | ✅ |

`cd backend; ruff check .; pytest -q` → all green; logs needs no broker.

## Reconciliations (vs LOGS.md, locked with the user)
- **Permissions** permission-first: read errors/actions/stats = `DIAGNOSTICS.VIEW`;
  DELETE = `DIAGNOSTICS.PURGE`. `action_log.role` is the role string.
- **Topics** our tree: `bridge.subscribe("diag")` + `("event/#")` (station-relative).
- **Query** logs-side filtering; additive `Repository.query(until=…)`; `(ts,id)`
  cursor. `Repository.delete(type, before_ts)` is the sanctioned non-append op
  (pruning + admin purge only).

## Manual
```pwsh
cd backend; python run.py
# admin (super_admin -> DIAGNOSTICS.*) token:
$r = irm localhost:8000/auth/login -Method Post -ContentType application/json `
     -Body '{"username":"admin","credential":{"password":"admin"}}'
$h = @{ Authorization = "Bearer $($r.token)" }
irm "localhost:8000/logs/errors?level=warning" -Headers $h
irm "localhost:8000/logs/actions?action=auth." -Headers $h   # once Auth calls record_action
irm "localhost:8000/logs/stats" -Headers $h
```

## Wiring notes / what it unlocks
- The sink registers on `core.diag` at init — every `diag.*` persists once logs is
  active, zero call-site changes. LabVIEW diag persists the same way once the
  Bridge publishes `tmf/{station}/diag` (addendum §5a).
- Run lifecycle: logs subscribes `event/#`, maps `run-started/finished/aborted` →
  `record_action(controller, run.*, run_id, success)`. Independent of the `runs`
  module (which persists `run` records from the same events).
- Siblings record actions via `core.get_contract("logs").record_action(principal,
  …)` — e.g. Auth's audit trail. Not retrofitted yet.

## Deferred (LOGS §11)
`jsonl` variant, `GET /logs/timeline`, frontend (diag viewer), the LabVIEW emit
itself, and age-based forced-reset. Thread-safe sink enqueue is a later harden
(assumes diag on the event loop).

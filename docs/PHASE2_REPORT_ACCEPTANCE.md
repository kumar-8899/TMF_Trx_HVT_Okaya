# Phase 2 — Report / Analytics acceptance

Last business module (PRINCIPLES build order step 2). Assembles a run report when
a run finishes and routes it to configurable **sinks**; SQLite is the always-on
queryable system-of-record, folder/MySQL are result-routed MES mirrors.

## Status

| Criterion | Proven by | Status |
|---|---|---|
| Module activates via gate; license-flip off | gate + e2e | ✅ |
| run-finished → report assembled from run_event history | `modules/report/tester` + e2e | ✅ |
| SQLite sink = queryable store (GET /reports, /{run_id}) | tester + e2e | ✅ |
| Folder sink routes by PASS/FAIL (json/csv) | tester | ✅ |
| Multiple sinks at once; sqlite forced present | tester | ✅ |
| MySQL sink fails loud (seam built, deferred) | tester | ✅ |
| Analytics: counts/yield/by-recipe/by-result | tester + e2e | ✅ |
| Export JSON/CSV, gated REPORT.EXPORT | tester | ✅ |
| Permission gates (REPORT.VIEW/EXPORT) | tester | ✅ |
| Full app: LV events → report → REST | `tests/test_report_e2e.py` | ✅ |

`cd backend; ruff check .; pytest -q` — green; report path needs no broker
(standalone), e2e uses the vendored Mosquitto.

## Config (app.example.json)
```json
{ "id": "report", "variant": "standard", "config": {
  "schema_version": 1,
  "sinks": [
    { "type": "sqlite", "when": "all" },
    { "type": "folder", "when": "fail", "path": "data/reports/fail", "format": "csv" },
    { "type": "folder", "when": "pass", "path": "data/reports/pass", "format": "json" }
  ] } }
```
Every finished run drops a PASS/FAIL file for MES while SQLite stays queryable.

## REST
- `GET /reports` (filters: since/until/recipe_id/result) — REPORT.VIEW
- `GET /reports/{run_id}` — REPORT.VIEW
- `GET /reports/analytics?since=&until=&recipe_id=` — REPORT.VIEW
- `GET /reports/{run_id}/export?format=json|csv` — REPORT.EXPORT

## Deferred
- **MySQL sink**: driver dep + live MySQL; seam built, fails loud if selected.
- **PDF/HTML** report rendering: future Report variants (need a render lib).
- Real run data needs the LabVIEW controller emitting `event/run-*`; tests use
  synthetic/fake-LV events.

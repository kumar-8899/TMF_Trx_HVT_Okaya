# REPORT_STORE.md — Reports on a professional DB (MySQL / SQL Server)

Reports are business-critical and high-volume (millions/year per station), so they live
in a **dedicated relational store on a professional DB server**, not the local SQLite
`records` envelope. Everything else (runs, config, health, auth, diagnostics) stays on
local SQLite — this is scoped to reports.

## Store model
- **Pro DB = system of record.** MySQL or SQL Server, chosen per deployment.
- **Local SQLite outbox = write-ahead spool.** Run-finish writes the assembled report to
  a small local outbox (`data/report_outbox.sqlite`) FIRST, then a background forwarder
  pushes it to the pro DB and retries on failure. Testing never blocks on, and never
  loses a report to, a DB/network outage.
- **Clean slate:** local SQLite reports were purged on cut-over; new reports go to the
  pro DB only.

## Schema (SQLAlchemy Core — one DDL for both providers)
Normalized so per-application test parameters are **rows, not columns** — no per-app DDL.
Tables are **prefixed `tmf_`** so they never collide with a client's existing tables
(e.g. a LabVIEW app's own `report` table) in a shared database.
- `tmf_report` (header, one row/run): `run_id` (PK), station, serial_no, model, operator,
  recipe_id, recipe_version, result, started_ts, finished_ts, business_day, shift_label,
  created_at. Indexed on business_day / model / shift_label / result / started_ts.
- `tmf_report_result` (child, one row/test): id, run_id (FK→tmf_report, CASCADE), seq,
  test_name, test_group, expected, measured, result, unit, cycle_time_ms. Indexed on
  run_id / test_name.

`SQLAlchemy Core` gives a dialect-agnostic schema + query layer; the sync engine runs in
a thread executor. Drivers are lazy: **MySQL** `mysql+pymysql`, **SQL Server**
`mssql+pyodbc` (needs the OS *ODBC Driver 18 for SQL Server*). Install per deployment:
`pip install .[report-db]`.

## Analytics scale
Aggregation runs on the DB server (`GROUP BY` over indexed columns), so dashboards touch
summaries, not millions of raw rows. Headline KPIs + by-day/model/shift + parameter Pareto
are exact SQL; unit-level detail (FPY p-chart, cycle I-MR) reads a bounded set of
lightweight `report` header rows and sets `detail_truncated` when capped (narrow the range
for exact detail).

## Configure (Settings → Report database, super_admin)
`GET/PUT /reports/db-config` (password redacted on read) + `POST /reports/db-config/test`
(connect + `SELECT 1` + create schema → honest verdict). The connection config is stored
locally; the password is kept station-local. Pick provider → host/port/database/user/
password (+ ODBC driver for SQL Server) → **Test connection** (creates tables) → Save.

## Resilience
If the DB is unreachable, reports queue in the outbox (`/reports` + Analytics show a "not
configured / queued" state); when the DB returns, the forwarder drains the queue. The
report module `health()` reports the outbox backlog.

## Follow-ups (not built)
Encryption-at-rest for the stored DB password (station-local for now); a central
multi-station BI warehouse; async mssql driver (sync-in-executor is used today).

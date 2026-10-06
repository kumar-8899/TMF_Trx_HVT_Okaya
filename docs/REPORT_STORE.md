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

## Bulk export (`modules/report/exporters/`, `REPORT.EXPORT`)
`GET /reports/full/export?<filters>&format=xlsx|tdms|csv&fields=…&columns=…&save=` exports the
filtered **matrix** (`ReportStore.full_matrix`, newest 20,000 runs; the response says when capped).
`GET /reports/export/formats` is the catalog the UI builds its controls from.

- **Layout contract (xlsx)** = the customer's `Report Template.xlsx`: row 1 = the fixed DUT columns
  (`serial_no, model, recipe_id, result, business_day, shift_label, date, time, operator, cycle_s`) then one
  **merged** header per test; row 2 = the parameter sub-headers; data from row 3. `date`/`time` come from the
  run's finish time (station-local zone), `business_day` is the shift-aware day. `cycle_s` and per-test
  Cycle Time are Excel durations; `measured` is a number when numeric. A single selected field = no merge.
- **Parameter fields** (`expected, measured, result, cycle`) are selectable; an unselected field is absent under
  **every** test. At least one is required (else 422). `columns` selects DUT columns (`station`, `run_id`
  are available, off by default).
- **TDMS** = flat single group `Reports`: fixed columns, then `"<test> - <Field label>"` channels, all equal
  length (row *n* = DUT *n*). Measured/Cycle are float64 (NaN = no value; seconds), Expected/Result strings; a
  measured channel with any non-numeric value is written as strings. Root properties carry station,
  export time, filters, tests and fields. A zero-row export writes empty float channels (nptdms cannot type
  an empty string channel).
- **Limits:** Excel 16,384 columns and a 3 M-cell cap (merged headers need openpyxl's in-memory mode) → a clear
  422; `format=csv` (default, legacy flat CSV) is unchanged. A test name repeated inside one run keeps its last
  occurrence (shared with the Full view).
- **Adding a format** = a module with `build(matrix, spec, meta) -> bytes` + one `register_format(...)` in
  `exporters/__init__.py`; the API, catalog and UI dropdown pick it up. Deps `openpyxl` + `nptdms` (numpy) are
  runtime dependencies and imported lazily.

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

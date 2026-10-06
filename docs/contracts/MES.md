# Contract — `mes` (MES Interlock)

Cross-station interlock: gate a run on the **previous** stage's result, and
**publish** this stage's result for the **next** stage. The transport is
pluggable: **folder** (file handoff) and **database** (customer tables) ship; XML is
future work behind the same seam. Entitlement key `mes`. Fills the optional `core.interlock` port.

## Two directions
- **Inbound gate** — before testing serial *S*, confirm *S* passed the previous
  stage. Missing → `gate.on_missing`; not allowed → block; source unreadable → `gate.on_error`.
- **Outbound publish** — on `run-finished`, **immediately** write *S*'s result (+ identity) so the
  next stage can gate on it. **Loud on failure** (below). No queue, no outbox, no silent retry.

Each direction has its own switch (`gate.enabled`, `publish.enabled`); a disabled direction keeps its
settings but does nothing and raises no alerts.

## The seam (pluggable transport)
`MesProvider` (modules/mes/providers/base.py):
- `check_upstream(serial) -> InterlockResult{allowed, prior_result, detail}`
- `publish_result(serial, result, payload)` — **raises** on failure
Providers: **folder** (`FolderProvider`), **database** (`DatabaseProvider` = `DbInbound` + `DbOutbound`).
Selected by `provider`, switchable at runtime (Config → MES) — `DefaultMes._rebuild_provider()`.
Add a type = one class + a factory entry in `providers/__init__.py`.

### Folder transport
Each stage writes `{downstream_dir}/{PASS|FAIL}/{serial}.json`. The next stage's
`upstream_dir` = the previous stage's `downstream_dir`; a unit proceeds only if
`{upstream_dir}/PASS/{serial}.json` exists. Payload: the outbound row below + `serial`, `result`, `written_ts`.

### Database transport

**Shared plumbing** is `core/services/dbconn.py` (URLs, engines with a connect timeout, create-database,
connection check, listing databases / tables+views / columns, distinct values, a probe). Modules depend on
core, not on each other, so `report` and `mes` both use it. MySQL (`mysql+pymysql`) and SQL Server
(`mssql+pyodbc`, ODBC Driver 18); sqlite is for tests / local files.

**Inbound — read-only.** Config `database.inbound`:

| Key | Meaning |
|---|---|
| `connection` | `{provider, host, port, user, password, odbc_driver}` |
| `database`, `table` | where the status lives; table may be a view; `schema.table` for non-default schemas |
| `serial_column` | the DUT serial / barcode |
| `status_column` | the previous stage's result |
| `allow_value` | the value that means *allowed* — **anything else blocks** |
| `ignore_case` | compare trimmed text case-insensitively (default true) |
| `latest_by` | ordered columns, newest first (`[date_col, time_col]` for separate date and time) |

`SELECT status FROM table WHERE serial = :s [ORDER BY latest_by… DESC LIMIT 1]`, built with SQLAlchemy Core
`table()/column()` (parameterised, quoted per dialect, **no reflection** — so names typed by hand work).
Decision: no row → `gate.on_missing`; with `latest_by` the newest row decides; **without** it, with several rows,
*every* row must equal `allow_value` (fail-safe). Any error/timeout → `gate.on_error` (default **block**) with the
database error in the 409 shown to the operator. `latest_by` sorts as the DB sorts the column type
(real DATE/TIME/DATETIME or ISO text; `dd/mm/yyyy` text would sort wrongly).

**Outbound — one table, one row per run.** Config `database.outbound`: `same_as_inbound`, `connection`,
`database`, `table`, `column_map {field → column}`. Row = the report **header** (no per-test data), registry
`providers/db_schema.MES_FIELDS`: `run_id*, station, serial_no*, model, operator, recipe_id, recipe_version,
result*, started_ts, finished_ts, business_day, shift_label, created_at` (\* required to be mapped; `run_id`
keys the write). `business_day`/`shift_label` come from `core.get_contract("config").shift_for`, `model` from
the `recipe` contract (both optional, with fallbacks).
- A **new** table is created from that schema; an **existing** table is mapped (auto-match by name,
  remappable, optional fields skippable). `epoch` fields are converted to datetime/date for DATETIME/DATE
  target columns; `business_day` to a date for DATE columns.
- Write = delete-by-`run_id` + insert in one transaction → idempotent, so a Retry never duplicates.
- Creating the database/table and adding columns happen **only** through the explicit
  `outbound/ensure` action — never while publishing.
- `validate()` reports missing columns, unmapped required fields and **NOT NULL columns without a default
  that are not mapped** (they would make every INSERT fail).

**Passwords** follow the report convention: stored in the station record (`mes_db_config`), never returned by
GET (`has_password`), a blank password on write keeps the stored one — **only when the host/user/provider/port
are unchanged** (a stored password is never sent to a different server).

## Failure semantics (outbound) — loud, no outbox
On any publish failure (any transport): `diag.error("mes","outbound push failed", run_id, serial, error)`;
module health → DEGRADED; a tiny `mes_push` record `{run_id, serial, result, status:"failed", error, ts}` is kept
(**status only — no payload copy, nothing is queued**). The UI prompts on every screen (`MesAlertDialog`,
driven by `GET /mes/alerts`, because the stream hub is latest-wins with no replay). **Retry** rebuilds the row from
the run record and sends it; **Dismiss** gives up (confirmed in the UI, audited as a warning with the user). No
automatic retry.

## Integration
- **Port:** the module registers `core.interlock.check`. `runs.run_start` calls it
  with the resolved serial **before** creating the run; not allowed →
  `InterlockError` → **HTTP 409**. No MES loaded ⇒ port is fail-open (allowed).
- **Publish:** the module subscribes `event/run-finished`, builds the row from the event + run record
  (waiting briefly if the runs module hasn't written its record yet) and publishes (when enabled).

## Config
```jsonc
{ "stage": "st1", "provider": "folder|database",
  "gate":    { "enabled": false, "on_missing": "block", "on_error": "block" },
  "publish": { "enabled": false },
  "folder":  { "upstream_dir": "data/mes/upstream", "downstream_dir": "data/mes/downstream" },
  "database": { "inbound": { … }, "outbound": { … } } }      // normally set in Config → MES, not app.json
```
Loaded but inactive by default. Provider, switches, policies and the database settings are edited at
runtime from **Config → MES** and persisted as `mes_setting` / `mes_db_config` records (those override the
`app.json` defaults).

## HTTP surface
All gated `SYSTEM.SETTINGS` except alerts (`TEST.RUN`).

| Method | Path | Behaviour |
|---|---|---|
| GET | `/mes/status` | provider, flags, policies, per-direction readiness, `failed_pushes` |
| PUT | `/mes/config` | `{ gate_enabled?, publish_enabled?, provider?, on_missing?, on_error? }` → persist + apply (422 on bad values) |
| GET / PUT | `/mes/db-config` | redacted read (+ `fields` catalog) / partial merge write; provider is rebuilt |
| POST | `/mes/db/test` | `{side, connection, same_as_inbound?}` → connect check |
| POST | `/mes/db/databases` · `/tables` · `/columns` · `/values` | listings — **never fail**: `{ok:false, items:[], detail}` so the UI falls back to manual entry |
| POST | `/mes/db/verify` | confirm hand-typed table/column names (`SELECT … LIMIT 1`) |
| POST | `/mes/db/inbound/check` | `{serial, inbound?}` dry run of the gate on the draft; no side effects |
| POST | `/mes/db/outbound/validate` · `/ensure` | does the table fit / create it, add missing columns (`add_missing`) |
| GET | `/mes/alerts` | pending outbound failures (`TEST.RUN`) |
| POST | `/mes/alerts/{run_id}/retry` · `/dismiss` | re-send from the run record / give up (audited) |

## Standalone test
`core + mes + :memory: db` with sqlite files standing in for MySQL/SQL Server —
`modules/mes/tester/test_mes.py` (folder) and `test_mes_db.py` (inbound allow/block/latest-by/error,
outbound create/map/idempotent/validate, loud failure + retry + dismiss, redaction, discovery,
REST, runs→409 integration); `tests/test_dbconn.py` (URLs, dialect SQL strings, quoting).
MySQL / SQL Server specifics (`SHOW DATABASES`, `sys.databases`, `ALTER TABLE … ADD`, ODBC) are asserted
at string level only — **verify on the real servers**.

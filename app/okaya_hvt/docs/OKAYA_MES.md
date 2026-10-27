# Okaya MES table (`okaya_mes`)

Okaya's MES already holds the results of three older benches in ONE table, one **wide** row per run (`txr_testtable`).
This bench writes the **same table**, not the framework's header-only MES row, so it has its own app-owned module:
`backend/modules/okaya_mes/` + the page **MES (Okaya table)** (`/app/okaya-mes`).
The customer's column list is committed as [okaya_mes_txr_testtable_hv.xlsx](okaya_mes_txr_testtable_hv.xlsx) and a test
asserts the module writes exactly those 32 columns in that order.

> The framework `mes` module stays as it is (folder provider, publish **OFF**). **Never turn its publish on against this
> table**: it would try to write its header row (it needs a `run_id` column Okaya's table does not have) and raise a failure.

## The row

All columns are `varchar(50)` except `date_time` (`datetime`).

| Column(s) | Value |
|---|---|
| `date_time` | run **finish** time, local, microseconds dropped |
| `serial_no` | the run's serial (barcode) — a run without one is skipped with a warning |
| `model_name` | the **recipe ID as text** (`001`, leading zeros kept) |
| `test_time` | run duration `m:ss`, minutes right-aligned to 2 (`' 1:15'`) |
| `operator_name` | the logged-in operator |
| `station_name` | configurable on the page (default `HV Testing`) — tells these rows apart from the older benches' |
| `hv_<pair>_winding_min / _max / _actual / _result` | per test, see below |
| `result` | `Pass` / `Fail` for the run |
| `failed_test` | the column **stem** of the FIRST failed test in execution order (`hv_pri_to_sec_winding`), else SQL NULL |

| Test (recipe group) | Column stem |
|---|---|
| Primary to Secondary (`pri_sec`) | `hv_pri_to_sec_winding` |
| Primary to Core (`pri_core`) | `hv_pri_to_core_winding` |
| Secondary to Core (`sec_core`) | `hv_sec_to_core_winding` |
| Feedback to Core (`fb_core`) | `hv_feedback_to_core_winding` |
| Primary to Feedback (`pri_fb`) | `hv_primary_to_feedback_winding` |
| Secondary to Feedback (`sec_fb`) | `hv_secondary_to_feedback_winding` |

Per test: `_min` is the recipe minimum, **`0` when the recipe has none** (the hipot recipe only sets a maximum); `_max` the
limit; `_actual` the reading in mA (`ERROR` when the tester failed); `_result` `Pass` / `Fail`.
A test that **did not run** (not in the recipe, or skipped by *Stop on first failure*) is **NULL in all four columns** (the old
`NaN` placeholder is not used). Numbers are short decimals (`0`, `10`, `0.052`).
Tests are matched by step id (`pri_sec_hipot`), then by name (the readable label, or the pre-2026-10 `<key>_leakage_current`).

## Behaviour

* **Instant and loud**, like the framework MES: the row is written the moment `run-finished` arrives. A failure is never
  queued or retried silently — it stays under **Failed deliveries** on the page (Retry / Dismiss), is logged as an error, and
  the module's health is DEGRADED until it is delivered or dismissed. Retry rebuilds the row from the run record.
* **Waits for a complete run record.** `run-finished` and the last `test-result` reach the runs module back to back, so the row
  is built only once the run record is marked `finished` AND holds as many results as there were `test-result` events (up to
  `complete_timeout_s`, default 5 s). If it never completes the write FAILS loudly ("2 of 3 test results stored — nothing
  written") and Retry rebuilds it; a partial row is never written. (Reading the record immediately wrote the LAST test as NULL.)
* **Idempotent**: the table has no run id, so a row is identified by `(serial_no, date_time)`. A retry or re-send **replaces**
  the row; re-testing the same serial later has a new finish time and adds a new row.
* The module only ever deletes + inserts that one row. **Create table** makes a NEW table (never alters an existing one).
* **Check table** names any missing column, a non-datetime `date_time`, and NOT NULL columns it never fills.
* **Check one run** previews the exact row for a run id (no database involved) and can **Send now** — also the way to
  backfill runs made before the module was switched on.

## Setting it up on a station

1. Install a build that contains the module (app 1.0.12 or later).
2. A frozen install never reconciles its live config, so the module is "not licensed" until two files get one additive entry
   each. With the station **closed**, run (Windows PowerShell, as the station's user):
   `app\okaya_hvt\tools\enable_okaya_mes.ps1 -InstallDir "C:\Okaya HVT Testbench\OkayaHVTTestbench"` (add `-WhatIf` to preview).
   It backs up `config\app.json` and `config\license.json`, adds `okaya_mes` to both, and is safe to run twice.
   (In a source checkout `python -m tools.config_doctor --apply` does the same.)
3. Start the station → sidebar **MES (Okaya table)** (needs `SYSTEM.SETTINGS`, i.e. super_admin).
4. Enter the MES server (SQL Server / MySQL), **Test connection**, pick the database and table, set the station name, **Save**.
5. **Check table** (must say *table fits*). Then preview a recent run, **Send now** for ONE run, and compare the row in the
   table with the preview and the template. Only then switch **Send results** On.

## Not verified here

Developed and tested against SQLite (SQLAlchemy Core is dialect-agnostic) and the full app. **Not run against Okaya's real SQL Server**:
check step 5 above with the real driver (`datetime` binding, the legacy "SQL Server" ODBC driver) before relying on it, and
read the result back with Okaya's own tooling. Operators (`TEST.RUN` without `SYSTEM.SETTINGS`) cannot open the page: the
failure is visible to an admin there, in the Logs page (`okaya_mes` errors) and as a DEGRADED health check.

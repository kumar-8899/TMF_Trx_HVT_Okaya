# Report rows - PASS / FAIL / INFO (contract)

Applies to every consumer of a run's result rows: the report store (`tmf_report_result`), the Reports "Full view",
xlsx/TDMS export, the KPI dashboard, the parameter Pareto and the in-memory analytics. Storage layout: `REPORT_STORE.md`.
Event shape: `MQTT_MESSAGES.md` section 3.2.

## 1. What a row is

One `test-result` event = one row = one named outcome of one step: `{test_name, expected, measured, result, unit,
cycle_time_ms, step_id, attempt[, message]}`. A step emits a row per `Measurement` it returns; only the **final**
attempt of a retried step is reported (a flaky first attempt is visible in the event stream, never in the report).

## 2. `result` values

| Value | Meaning | Counted in yield / Pareto / analytics? |
|---|---|---|
| `PASS` (or `PASS...`, e.g. `PASS (waived)`) | a measured outcome within limits | yes, as a pass |
| `FAIL` | a measured outcome outside limits, **or the step could not produce one** (see 3) | yes, as a failure |
| `INFO` | **context, not a verdict**: `set_output` writes, `prompt_operator` answers, any row a step records without limits | **never** - not a pass, not a failure |

A blank or unknown `result` is a **failure** (fail-closed: a row nobody can classify must not inflate yield).
The single definition is `modules/report/analytics.py::row_is_failure()` (in-memory paths) and
`func.upper(result) != 'INFO'` beside `NOT LIKE 'PASS%'` in the SQL Pareto
(`store.py`); both are covered by tests (`test_info_rows_are_not_failures`, the store tests).

Before v1.31.0 INFO rows were counted as failures, so a run that passed overall still put its `set_output` steps at
the top of the failure Pareto.

Not changed: **cycle time** still sums every row's `cycle_time_ms`, INFO included (a `set_output` takes real
time). Whether xlsx/TDMS export and the Full view should omit INFO rows is an open option - the default is
unchanged (INFO rows are included).

## 3. The invariant: a FAIL verdict always has a FAIL row

> Whenever a run's verdict is `FAIL`, at least one emitted row has `result: FAIL`.

The sequencer enforces it (`sequencer.py::_attempt`). A non-composite step that **raises** (not an abort) used to
leave an empty measurement list - a FAIL verdict with no failing row, invisible in the report and in yield. It now
synthesizes one row:

| Field | Value |
|---|---|
| `test_name` | `params.name`, else `params.signal`, else `params.read`, else the `step_id` |
| `measured` | `"ERROR"` |
| `expected` / limits | from `params.min` / `max` / `expected` when present |
| `result` | `FAIL` |
| `message` | the cause (also on the `step-completed` event and in a `warning` diagnostic `step.end`) |

Composite steps (`group`, `repeat`, `if`, `sweep`) never synthesize - their children do. A step that raises
`StepAborted` is an abort, not a failed reading. The `message` of a failing row rides on the `test-result` event, so
the Runs record keeps the cause.

## 4. Reading a signal can be retried

`measure_and_compare` takes `retries` (0-5, default 0) and `settle_s` (default 0.5): a read that raises, or reads
out of limits, is re-read after `settle_s`; only the last attempt becomes the row. If every attempt raised, the row
is the `ERROR` row above. The step-level `retry_count` still re-runs the **whole** step and is the wrong tool for a
flaky read.

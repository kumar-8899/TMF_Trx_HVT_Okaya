# Reports

Per-run reports, stored on the professional report database.

![Reports — run outcomes and yield](asset:reports)

## Run reports list
Columns: **Serial No · Model · Recipe · Result · Cycle (s) · Finished**.
- **Model** comes from the recipe (the DUT type name — set it on the recipe).
- **Cycle (s)** is the total test cycle time in seconds (sum of each test row's cycle time).

Click a row to see that run's **test results**, and export it (JSON / CSV).

## Filters
- **Serial No** — search (partial match).
- **Model** — dropdown of the models present in reports.
- **Result** — PASS / FAIL / ABORTED.
- **From / To (business day)** — date range on the **business day** (shift-aware, so an
  overnight shift counts to the day it started; see Shifts).

## Paging
Reports are **paged** — pick the rows-per-page (25 / 50 / 100 / 200) and use **Prev /
Next**. The list shows `x–y of total`.

## Full view + export
**Full view** opens a flattened **test-data matrix**: one row per run, with the fixed
fields **plus a column for every test parameter** in the filtered set. Each cell merges
that parameter's **measured** value with its **expected**, **result**, and **cycle time
(s)**. Use it to compare many units across all parameters at once.

**Export CSV (all filtered)** saves the whole filtered set as one CSV (fixed fields +
every test parameter) for offline analysis — not just the current page. The file is written
to this PC's **Downloads** folder (e.g. `Downloads\reports-full-<date>-<time>.csv`) and a green
banner confirms the exact path. A single run's **Export JSON / CSV** (from its results dialog)
saves the same way. Files are timestamped, so an export never overwrites an earlier one.

> Reports are stored on a MySQL / SQL Server database (Settings → Report database). If it
> isn't configured, the page shows a note and new reports queue locally until it is.

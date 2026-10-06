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

**Export (all filtered)** saves the whole filtered set — not just the current page — as one
file for offline analysis. Pick the **Format** first:

- **Excel (.xlsx)** — one row per unit. The first columns are the unit's details (`serial_no`,
  `model`, `recipe_id`, `result`, `business_day`, `shift_label`, `date`, `time`, `operator`,
  `cycle_s`); after them every **test** gets its own block under one merged heading, with the
  sub-columns **Expected Value · Measured Value · Result · Cycle Time**. PASS / FAIL cells are
  coloured, dates and times are real Excel dates and times, and measured values are numbers.
- **TDMS (.tdms)** — the same table as a flat list of channels in one group (`Reports`), every
  channel the same length (row *n* of each channel is unit *n*). The test columns are named
  `<test> - Measured Value`, `<test> - Result`, and so on. Measured values and cycle times are
  numbers (times in seconds); if a test's measured value is ever text (for example `n/a`) that
  column is saved as text instead, so nothing is lost. Open it in LabVIEW, DIAdem or Excel's
  NI add-in.

**Test columns** chooses which of the four sub-columns go under *every* test. Untick **Result**
and no test has a Result column; at least one must stay ticked. Your choice is remembered on
this PC.

The file is written to this PC's **Downloads** folder (e.g.
`Downloads\reports-full-<date>-<time>.xlsx`) and a green banner confirms the exact path. If
more runs match than the export limit (20,000) the banner says only the newest were saved —
narrow the filters (dates, model) to get the rest. Excel also has a hard limit of 16,384
columns; a huge test list with all four sub-columns ticked can exceed it, in which case untick
some sub-columns or use TDMS. A single run's **Export JSON / CSV** (from its results dialog)
is unchanged. Files are timestamped, so an export never overwrites an earlier one.

> If the same test name appears more than once in one run (for example a retried step), the
> export — like the Full view — shows the last result for that name.

> Reports are stored on a MySQL / SQL Server database (Settings → Report database). If it
> isn't configured, the page shows a note and new reports queue locally until it is.

"""Okaya MES wide row — the customer's legacy `txr_testtable` layout, filled from one run record.

Okaya's MES already holds three older benches' results in ONE table with one WIDE row per run
(date_time, serial_no, ... then min / max / actual / result for every test, then the overall `result` and
`failed_test`). This bench must write that same table, not the framework's header-only MES row, so the
row is built here from the run record's per-test results (`run.results`, one entry per `test-result`).

Everything is `varchar(50)` except `date_time` (a real datetime). Rules (agreed with the user):

* `model_name`   the recipe ID as TEXT (`001`, not 1 — leading zeros survive).
* `date_time`    the run FINISH time, local, microseconds dropped — it is half of the idempotency key
                 (a retry must find and replace the row it already wrote), and SQL Server `datetime`
                 only keeps ~3 ms anyway.
* `test_time`    run duration as ``m:ss`` with the minutes right-aligned to 2 (`' 1:15'`).
* per test       `*_min` is 0 when the recipe gives no minimum (the legacy rows show 0 / 10), `*_max` the
                 limit, `*_actual` the reading (`ERROR` when the tester failed), `*_result` Pass / Fail.
* a test that did not run (not in the recipe, or skipped by stop-on-first-failure) is NULL in all four.
* `result`       Pass / Fail for the run.
* `failed_test`  the column STEM of the FIRST failed test in execution order (`hv_pri_to_sec_winding`),
                 or NULL when nothing failed.

Pure functions only: no database, no clock — unit-tested against the customer's sample row.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

# (test key = the recipe group / step-id prefix, column stem, human label, pre-2026-10 result name)
HV_TESTS: tuple[tuple[str, str, str, str], ...] = (
    ("pri_sec", "hv_pri_to_sec_winding", "Primary to Secondary", "pri_sec_leakage_current"),
    ("pri_core", "hv_pri_to_core_winding", "Primary to Core", "pri_core_leakage_current"),
    ("sec_core", "hv_sec_to_core_winding", "Secondary to Core", "sec_core_leakage_current"),
    ("fb_core", "hv_feedback_to_core_winding", "Feedback to Core", "fb_core_leakage_current"),
    ("pri_fb", "hv_primary_to_feedback_winding", "Primary to Feedback", "pri_fb_leakage_current"),
    ("sec_fb", "hv_secondary_to_feedback_winding", "Secondary to Feedback", "sec_fb_leakage_current"),
)
_PARTS = ("min", "max", "actual", "result")
HEADER_COLUMNS = ("date_time", "serial_no", "model_name", "test_time", "operator_name", "station_name")
#: every column of the customer's table, in its own order (the template `txr_testtable_hv.xlsx`)
COLUMNS: tuple[str, ...] = (
    *HEADER_COLUMNS,
    *(f"{stem}_{p}" for _k, stem, _l, _o in HV_TESTS for p in _PARTS),
    "result", "failed_test",
)
DATETIME_COLUMNS = ("date_time",)
TEXT_LEN = 50                                   # varchar(50) everywhere except date_time
DEFAULT_STATION_NAME = "HV Testing"

_BY_KEY = {k: stem for k, stem, _l, _o in HV_TESTS}
_BY_NAME = {**{lbl.lower(): stem for _k, stem, lbl, _o in HV_TESTS},
            **{old.lower(): stem for _k, stem, _l, old in HV_TESTS}}


def _txt(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s[:TEXT_LEN] if s else None


def fmt_number(v: Any) -> str | None:
    """A reading / limit as the short decimal text the legacy rows hold (`0`, `10`, `0.52`, `215.4`).
    Non-numbers (`ERROR`) pass through as text; NaN / inf are NULL (the old `NaN` placeholder)."""
    if v is None or isinstance(v, bool):
        return None if v is None else ("1" if v else "0")
    if isinstance(v, (int, float)):
        f = float(v)
        if not math.isfinite(f):
            return None
        s = f"{round(f, 4):.4f}".rstrip("0").rstrip(".")
        return "0" if s in ("", "-0") else s
    return _txt(v)


def verdict(status: Any) -> str | None:
    """PASS -> Pass, FAIL -> Fail (the legacy casing); INFO / unknown -> NULL."""
    s = str(status or "").strip().upper()
    return {"PASS": "Pass", "FAIL": "Fail"}.get(s)


def test_time_text(started: Any, finished: Any) -> str | None:
    """Run duration as `m:ss`, minutes right-aligned to width 2 (`' 1:15'`, `'12:05'`)."""
    try:
        secs = float(finished) - float(started)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(secs) or secs < 0:
        return None
    m, s = divmod(int(round(secs)), 60)
    return f"{m:2d}:{s:02d}"


def finish_datetime(finished: Any) -> _dt.datetime | None:
    """Local wall-clock finish time without microseconds (the stable half of the idempotency key)."""
    try:
        return _dt.datetime.fromtimestamp(float(finished)).replace(microsecond=0)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def stem_for(result: dict) -> str | None:
    """Which HV column group a `test-result` belongs to: by step id (`pri_sec_hipot`), else by its name
    (the readable label, or the pre-2026-10 `<key>_leakage_current`)."""
    sid = str(result.get("step_id") or "")
    key = sid[:-len("_hipot")] if sid.endswith("_hipot") else sid
    if key in _BY_KEY:
        return _BY_KEY[key]
    for field in ("name", "test_name"):
        stem = _BY_NAME.get(str(result.get(field) or "").strip().lower())
        if stem:
            return stem
    return None


def build_row(run: dict, *, station_name: str | None = None) -> dict[str, Any]:
    """The wide row for one finished run (`run` = the run record's data). Every column of `COLUMNS` is
    present; anything with no value is None (SQL NULL)."""
    row: dict[str, Any] = {c: None for c in COLUMNS}
    row["date_time"] = finish_datetime(run.get("finished_ts"))
    row["serial_no"] = _txt(run.get("serial_no"))
    rid = run.get("recipe_id")
    row["model_name"] = _txt(rid)                                   # text, so '001' keeps its zeros
    row["test_time"] = test_time_text(run.get("started_ts"), run.get("finished_ts"))
    row["operator_name"] = _txt(run.get("operator"))
    row["station_name"] = _txt(station_name) or DEFAULT_STATION_NAME

    first_failed: str | None = None
    for r in run.get("results") or []:                              # execution order
        stem = stem_for(r)
        status = verdict(r.get("status") or r.get("result"))
        if stem is None:
            if status == "Fail" and first_failed is None:           # an unmapped test still names the failure
                first_failed = _txt(r.get("name") or r.get("step_id"))
            continue
        lim = r.get("limits") or {}
        has_limits = bool(lim) and (lim.get("min") is not None or lim.get("max") is not None
                                    or lim.get("expected") is not None)
        mn = lim.get("min")
        row[f"{stem}_min"] = fmt_number(mn if mn is not None else 0) if has_limits else None
        row[f"{stem}_max"] = fmt_number(lim.get("max")) if has_limits else None
        row[f"{stem}_actual"] = fmt_number(r.get("value", r.get("measured")))
        row[f"{stem}_result"] = status
        if status == "Fail" and first_failed is None:
            first_failed = stem

    row["result"] = verdict(run.get("result")) or _txt(str(run.get("result") or "").title())
    row["failed_test"] = first_failed
    return row

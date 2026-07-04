"""Test analytics over the report corpus (premium Analytics module).

Pure functions over a list of report dicts (as stored by the report module), so
they are trivially testable and independent of storage. The HTTP layer filters
the corpus and calls `build_dashboard`.

Definitions follow the Analytics design summary:
- A "unit" is a serial_number (falls back to run_id when a run had no barcode).
- First Pass Yield (FPY) = units whose FIRST attempt passed / distinct units.
- p-chart: daily FPY with center line p̄ and ±3σ control limits.
- Cycle time I-MR: individuals + moving-range control charts.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timezone


def result_is_pass(result) -> bool:
    return str(result or "").upper().startswith("PASS")


def _day(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _bday(r: dict) -> str | None:
    """Day-count key: the stamped business_day (shift-aware, spans midnight) when
    present, else the calendar date. Forward-only — old reports fall back cleanly."""
    return r.get("business_day") or _day(r.get("started_ts") or r.get("finished_ts"))


def _cycle_s(r: dict) -> float | None:
    """Run cycle time in seconds: finished-started, else sum of row cycle_time_ms."""
    s, f = r.get("started_ts"), r.get("finished_ts")
    if s and f and f >= s:
        return float(f) - float(s)
    rows = r.get("rows") or []
    ms = sum(float(x.get("cycle_time_ms") or 0) for x in rows)
    return ms / 1000.0 if ms else None


def _first_fail_test(r: dict) -> str | None:
    for row in r.get("rows") or []:
        if not result_is_pass(row.get("result")):
            return row.get("test_name") or "(unnamed)"
    return None if result_is_pass(r.get("result")) else "(unknown)"


def apply_filters(reports, *, since=None, until=None, model=None, operator=None, shift=None) -> list[dict]:
    out = []
    for r in reports:
        ts = r.get("finished_ts") or r.get("started_ts") or 0
        if since is not None and ts < since:
            continue
        if until is not None and ts > until:
            continue
        if model and r.get("model") != model:
            continue
        if operator and r.get("operator") != operator:
            continue
        if shift and r.get("shift_label") != shift:
            continue
        out.append(r)
    return out


def _units(reports) -> dict[str, list[dict]]:
    """Group reports by unit (serial_no, else run_id), each ordered by time."""
    by: dict[str, list[dict]] = {}
    for r in reports:
        key = r.get("serial_no") or r.get("run_id")
        by.setdefault(key, []).append(r)
    for runs in by.values():
        runs.sort(key=lambda r: r.get("started_ts") or r.get("finished_ts") or 0)
    return by


def _pareto(counter: dict[str, int]) -> list[dict]:
    items = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(counter.values()) or 1
    out, cum = [], 0
    for name, count in items:
        cum += count
        out.append({"name": name, "count": count, "cum_pct": round(100 * cum / total, 1)})
    return out


def _kpis(reports) -> dict:
    total = len(reports)
    passed = sum(1 for r in reports if result_is_pass(r.get("result")))
    aborted = sum(1 for r in reports if str(r.get("result")).upper() == "ABORTED")
    failed = total - passed - aborted

    units = _units(reports)
    first_pass = sum(1 for runs in units.values() if result_is_pass(runs[0].get("result")))
    retested = sum(1 for runs in units.values() if len(runs) > 1)
    n_units = len(units) or 0
    cycles = [c for c in (_cycle_s(r) for r in reports) if c is not None]

    return {
        "runs": total, "passed": passed, "failed": failed, "aborted": aborted,
        "yield": round(100 * passed / total, 1) if total else 0.0,
        "units": n_units,
        "fpy": round(100 * first_pass / n_units, 1) if n_units else 0.0,
        "retest_rate": round(100 * retested / n_units, 1) if n_units else 0.0,
        "avg_cycle_s": round(statistics.fmean(cycles), 1) if cycles else 0.0,
        "median_cycle_s": round(statistics.median(cycles), 1) if cycles else 0.0,
    }


def _fpy_pchart(reports) -> dict:
    """Daily FPY (first attempt per unit per day) + p-chart control limits."""
    daily: dict[str, dict] = {}
    for key, runs in _units(reports).items():
        first = runs[0]
        d = _bday(first)
        if d is None:
            continue
        cell = daily.setdefault(d, {"n": 0, "x": 0})
        cell["n"] += 1
        if result_is_pass(first.get("result")):
            cell["x"] += 1
    days = sorted(daily)
    sum_x = sum(daily[d]["x"] for d in days)
    sum_n = sum(daily[d]["n"] for d in days) or 1
    pbar = sum_x / sum_n
    series = []
    for d in days:
        n, x = daily[d]["n"], daily[d]["x"]
        p = x / n if n else 0.0
        sigma = (pbar * (1 - pbar) / n) ** 0.5 if n else 0.0
        series.append({
            "date": d, "n": n, "x": x, "p": round(100 * p, 1),
            "ucl": round(100 * min(1.0, pbar + 3 * sigma), 1),
            "lcl": round(100 * max(0.0, pbar - 3 * sigma), 1),
        })
    return {"series": series, "pbar": round(100 * pbar, 1)}


def _passfail_daily(reports) -> list[dict]:
    daily: dict[str, dict] = {}
    for r in reports:
        d = _bday(r)
        if d is None:
            continue
        cell = daily.setdefault(d, {"pass": 0, "fail": 0})
        cell["pass" if result_is_pass(r.get("result")) else "fail"] += 1
    return [{"date": d, **daily[d]} for d in sorted(daily)]


def _by_shift(reports) -> list[dict]:
    by: dict[str, dict] = {}
    for r in reports:
        s = r.get("shift_label")
        if not s:
            continue
        cell = by.setdefault(s, {"shift": s, "total": 0, "passed": 0, "failed": 0})
        cell["total"] += 1
        cell["passed" if result_is_pass(r.get("result")) else "failed"] += 1
    for c in by.values():
        c["yield"] = round(100 * c["passed"] / c["total"], 1) if c["total"] else 0.0
    return sorted(by.values(), key=lambda c: c["shift"])


def _by_model(reports) -> list[dict]:
    by: dict[str, dict] = {}
    for r in reports:
        m = r.get("model") or "(none)"
        cell = by.setdefault(m, {"model": m, "total": 0, "passed": 0, "failed": 0})
        cell["total"] += 1
        cell["passed" if result_is_pass(r.get("result")) else "failed"] += 1
    rows = list(by.values())
    for c in rows:
        c["fpy"] = round(100 * c["passed"] / c["total"], 1) if c["total"] else 0.0
    return sorted(rows, key=lambda c: c["total"], reverse=True)


def _cycle(reports, bins: int = 12) -> dict:
    cycles = [(r.get("finished_ts") or r.get("started_ts") or 0, c)
              for r in reports if (c := _cycle_s(r)) is not None]
    cycles.sort(key=lambda t: t[0])
    vals = [c for _, c in cycles]
    hist: list[dict] = []
    if vals:
        lo, hi = min(vals), max(vals)
        width = (hi - lo) / bins or 1
        counts = [0] * bins
        for v in vals:
            idx = min(bins - 1, int((v - lo) / width))
            counts[idx] += 1
        hist = [{"bin": round(lo + i * width, 1), "count": counts[i]} for i in range(bins)]

    # I-MR
    imr: dict = {"points": [], "xbar": 0.0, "ucl": 0.0, "lcl": 0.0, "mr_bar": 0.0, "mr_ucl": 0.0}
    if len(vals) >= 2:
        mrs = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
        xbar = statistics.fmean(vals)
        mrbar = statistics.fmean(mrs) if mrs else 0.0
        sigma = mrbar / 1.128 if mrbar else 0.0
        imr = {
            "points": [{"i": i + 1, "x": round(v, 2),
                        "mr": round(mrs[i - 1], 2) if i >= 1 else None} for i, v in enumerate(vals)],
            "xbar": round(xbar, 2),
            "ucl": round(xbar + 3 * sigma, 2), "lcl": round(max(0.0, xbar - 3 * sigma), 2),
            "mr_bar": round(mrbar, 2), "mr_ucl": round(3.267 * mrbar, 2),
        }
    return {"histogram": hist, "imr": imr}


def build_dashboard(reports, *, since=None, until=None, model=None, operator=None, shift=None) -> dict:
    rs = apply_filters(reports, since=since, until=until, model=model, operator=operator, shift=shift)

    fail_counter: dict[str, int] = {}
    param_counter: dict[str, int] = {}
    for r in rs:
        ff = _first_fail_test(r)
        if ff:
            fail_counter[ff] = fail_counter.get(ff, 0) + 1
        for row in r.get("rows") or []:
            if not result_is_pass(row.get("result")):
                name = row.get("test_name") or "(unnamed)"
                param_counter[name] = param_counter.get(name, 0) + 1

    return {
        "generated_ts": time.time(),
        "filters": {"since": since, "until": until, "model": model, "operator": operator, "shift": shift},
        "kpis": _kpis(rs),
        "fpy": _fpy_pchart(rs),
        "passfail_daily": _passfail_daily(rs),
        "failure_pareto": _pareto(fail_counter),
        "param_pareto": _pareto(param_counter),
        "by_model": _by_model(rs),
        "by_shift": _by_shift(rs),
        "cycle": _cycle(rs),
        "models": sorted({r.get("model") for r in reports if r.get("model")}),
        "operators": sorted({r.get("operator") for r in reports if r.get("operator")}),
        "shifts": sorted({r.get("shift_label") for r in reports if r.get("shift_label")}),
    }

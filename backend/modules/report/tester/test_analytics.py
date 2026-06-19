"""Unit tests for the analytics engine (pure functions over report dicts)."""

from modules.report.analytics import build_dashboard


def _report(run_id, serial, model, result, started, finished, rows=None, operator=None):
    return {
        "run_id": run_id, "serial_no": serial, "model": model, "operator": operator,
        "result": result, "started_ts": started, "finished_ts": finished,
        "rows": rows or [], "recipe_id": model,
    }


# two units of model A: SN1 fails then passes (retest), SN2 passes first time.
DAY = 1_700_000_000.0
REPORTS = [
    _report("r1", "SN1", "INV", "FAIL", DAY, DAY + 10, operator="op1",
            rows=[{"test_name": "OVP", "result": "PASS"}, {"test_name": "UVP", "result": "FAIL"}]),
    _report("r2", "SN1", "INV", "PASS", DAY + 100, DAY + 110, operator="op1",
            rows=[{"test_name": "OVP", "result": "PASS"}, {"test_name": "UVP", "result": "PASS"}]),
    _report("r3", "SN2", "INV", "PASS", DAY + 5, DAY + 12, operator="op2",
            rows=[{"test_name": "OVP", "result": "PASS"}]),
]


def test_kpis_fpy_and_retest():
    d = build_dashboard(REPORTS)
    k = d["kpis"]
    assert k["runs"] == 3 and k["units"] == 2
    assert k["passed"] == 2 and k["failed"] == 1
    assert k["fpy"] == 50.0          # SN1 first attempt failed, SN2 passed -> 1/2
    assert k["retest_rate"] == 50.0  # SN1 retested
    assert k["avg_cycle_s"] > 0


def test_failure_and_param_pareto():
    d = build_dashboard(REPORTS)
    # first-fail pareto: only r1 failed first on UVP
    assert d["failure_pareto"][0]["name"] == "UVP" and d["failure_pareto"][0]["count"] == 1
    assert d["failure_pareto"][0]["cum_pct"] == 100.0
    # param pareto: UVP failed once across rows
    assert d["param_pareto"][0]["name"] == "UVP"


def test_pchart_and_filters():
    d = build_dashboard(REPORTS)
    assert d["fpy"]["series"] and "ucl" in d["fpy"]["series"][0]
    assert d["by_model"][0]["model"] == "INV" and d["by_model"][0]["total"] == 3
    assert "op1" in d["operators"] and "op2" in d["operators"]
    # operator filter narrows the corpus
    only = build_dashboard(REPORTS, operator="op2")
    assert only["kpis"]["runs"] == 1


def test_cycle_imr_present():
    d = build_dashboard(REPORTS)
    assert d["cycle"]["histogram"]
    assert d["cycle"]["imr"]["points"] and d["cycle"]["imr"]["ucl"] >= d["cycle"]["imr"]["xbar"]

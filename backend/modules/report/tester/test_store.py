"""ReportStore tester — SQLAlchemy Core is provider-agnostic, so the schema + queries
run identically on sqlite (here) and on MySQL / SQL Server (verified by the user via
Settings → Test connection)."""

import pytest

from modules.report.store import ReportStore, StoreError, build_url


def _report(run_id, model, result, started, finished, serial=None, rows=None):
    return {"run_id": run_id, "station": "st1", "serial_no": serial or run_id, "model": model,
            "operator": "op1", "recipe_id": model, "recipe_version": 1, "result": result,
            "started_ts": started, "finished_ts": finished, "business_day": "2026-07-04",
            "shift_label": "Night", "rows": rows or []}


@pytest.fixture
async def store(tmp_path):
    s = ReportStore()
    s.configure({"provider": "sqlite", "path": str(tmp_path / "reports.sqlite")})
    await s.ensure_schema()
    yield s
    s.dispose()


async def test_write_header_and_result_rows(store):
    await store.write(_report("R1", "INV", "PASS", 100.0, 110.0, rows=[
        {"test_name": "OVP", "expected": "320", "measured": "319.4", "result": "PASS", "cycle_time_ms": 412},
        {"test_name": "UVP", "expected": "10", "measured": "9.9", "result": "FAIL", "cycle_time_ms": 88},
    ]))
    got = await store.get_report("R1")
    assert got["model"] == "INV" and got["result"] == "PASS"
    assert len(got["rows"]) == 2 and got["rows"][0]["test_name"] == "OVP"


async def test_write_is_idempotent(store):
    await store.write(_report("R2", "INV", "FAIL", 1, 2, rows=[{"test_name": "A", "result": "FAIL"}]))
    await store.write(_report("R2", "INV", "PASS", 1, 2, rows=[{"test_name": "A", "result": "PASS"}]))
    got = await store.get_report("R2")
    assert got["result"] == "PASS" and len(got["rows"]) == 1        # re-forward overwrote, no dupes


async def test_dashboard_and_list_from_sql(store):
    await store.write(_report("A", "INV", "PASS", 100, 110))
    await store.write(_report("B", "INV", "FAIL", 120, 130, rows=[{"test_name": "UVP", "result": "FAIL"}]))
    await store.write(_report("C", "DCX", "PASS", 140, 150))
    d = await store.dashboard()
    assert d["configured"] and d["kpis"]["runs"] == 3 and d["kpis"]["passed"] == 2
    assert d["kpis"]["yield"] == round(200 / 3, 1)
    by_model = {m["model"]: m for m in d["by_model"]}
    assert by_model["INV"]["total"] == 2 and by_model["DCX"]["passed"] == 1
    assert {s["shift"] for s in d["by_shift"]} == {"Night"}
    assert d["param_pareto"][0]["name"] == "UVP"                    # failing test row
    lst = await store.list_reports(model="INV")
    assert lst["total"] == 2 and lst["configured"]


async def test_unconfigured_is_safe():
    s = ReportStore()
    assert s.configured is False
    assert (await s.dashboard())["configured"] is False
    assert (await s.list_reports())["items"] == []
    assert await s.get_report("x") is None
    with pytest.raises(StoreError):
        await s.write(_report("z", "INV", "PASS", 1, 2))


async def test_test_connection_ok_and_bad(tmp_path):
    s = ReportStore()
    ok = await s.test_connection({"provider": "sqlite", "path": str(tmp_path / "t.sqlite")})
    assert ok["ok"] and ok["status"] == "pass"
    bad = await s.test_connection({"provider": "nope"})
    assert bad["ok"] is False


def test_url_builders():
    assert build_url({"provider": "mysql", "host": "h", "user": "u", "password": "p", "database": "d"}).drivername == "mysql+pymysql"
    assert build_url({"provider": "sqlserver", "host": "h", "database": "d"}).drivername == "mssql+pyodbc"

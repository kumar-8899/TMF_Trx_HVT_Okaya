"""okaya_mes — run-finished -> one wide row in the customer's table, loud failures, retry, REST.

A sqlite file stands in for Okaya's SQL Server (SQLAlchemy Core is dialect-agnostic; the SQL Server specifics
live in core/services/dbconn and are verified by the user on the real server)."""

import asyncio
import datetime as dt
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from core.framework.contract import CoreServices
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.okaya_mes import rowbuilder as rb
from modules.okaya_mes.variants.default import OkayaMes


def _conn(path) -> dict:
    return {"provider": "sqlite", "path": str(path)}


def _ts(*hms) -> float:
    return dt.datetime(2026, 10, 26, *hms).timestamp()


def _res(key, label, value, status="PASS", mx=10.0):
    return {"step_id": f"{key}_hipot", "name": label, "value": value, "unit": "mA", "status": status,
            "limits": {"min": None, "max": mx, "expected": None}}


RESULTS = [_res("pri_sec", "Primary to Secondary", 0.052), _res("pri_core", "Primary to Core", 12.5, "FAIL"),
           _res("sec_core", "Secondary to Core", 0.31)]


async def _build(tmp_path, *, enabled=True, with_table=True, table="txr_testtable"):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    events: list[dict] = []
    core = CoreServices(db=db, auth=TokenVerifier(), station="st1",
                        diag=Diagnostics("st1", "0.0.0", sinks=[events.append]))
    cfg = {"enabled": enabled, "station_name": "HV Testing", "table": table,
           "connection": _conn(tmp_path / "okaya.sqlite")}
    m = OkayaMes.construct(core, cfg)
    await m.init()
    if with_table:
        from modules.okaya_mes import writer
        writer.table_def(table).create(m._eng())
    return m, core, db, events


async def _seed_run(db, run_id="R1", serial="SN-1", results=None, result="FAIL", recipe_id="001"):
    await db.repo.put("run", {"run_id": run_id, "status": "finished", "serial_no": serial, "recipe_id": recipe_id, "operator": "admin",
                              "started_ts": _ts(18, 1, 29), "finished_ts": _ts(18, 2, 44), "result": result,
                              "results": RESULTS if results is None else results}, id=run_id, summary="run")


def _rows(tmp_path):
    con = sqlite3.connect(tmp_path / "okaya.sqlite")
    con.row_factory = sqlite3.Row
    out = [dict(r) for r in con.execute("SELECT * FROM txr_testtable ORDER BY date_time")]
    con.close()
    return out


async def _finish(m, run_id="R1", result="FAIL"):
    await m._on_event("event/run-finished", {"type": "run-finished", "payload": {"run_id": run_id, "result": result},
                                             "ts": _ts(18, 2, 44)})


# --- the write --------------------------------------------------------------------------------------

async def test_run_finished_writes_one_wide_row(tmp_path):
    m, _, db, events = await _build(tmp_path)
    await _seed_run(db)
    await _finish(m)
    (row,) = _rows(tmp_path)
    assert row["serial_no"] == "SN-1" and row["model_name"] == "001" and row["test_time"] == " 1:15"
    assert row["station_name"] == "HV Testing" and row["operator_name"] == "admin"
    assert row["hv_pri_to_sec_winding_actual"] == "0.052" and row["hv_pri_to_sec_winding_result"] == "Pass"
    assert row["hv_pri_to_core_winding_actual"] == "12.5" and row["hv_pri_to_core_winding_result"] == "Fail"
    assert row["hv_feedback_to_core_winding_result"] is None                 # not run -> NULL
    assert row["result"] == "Fail" and row["failed_test"] == "hv_pri_to_core_winding"
    assert set(row) == set(rb.COLUMNS)
    assert any(e.get("message") == "result written to the Okaya table" for e in events)
    await db.close()


async def test_a_retry_replaces_the_row_it_wrote_instead_of_duplicating(tmp_path):
    m, _, db, _ = await _build(tmp_path)
    await _seed_run(db)
    await _finish(m)
    await _finish(m)                                  # same run again (retry / re-delivery)
    assert len(_rows(tmp_path)) == 1
    await db.close()


async def test_retesting_the_same_serial_later_adds_a_new_row(tmp_path):
    m, _, db, _ = await _build(tmp_path)
    await _seed_run(db, "R1")
    await _seed_run(db, "R2")
    rec = await db.repo.get("run", "R2")
    rec["data"]["finished_ts"] = _ts(19, 30, 0)
    await db.repo.put("run", rec["data"], id="R2", summary="run")
    await _finish(m, "R1")
    await _finish(m, "R2")
    assert len(_rows(tmp_path)) == 2
    await db.close()


async def test_a_clean_run_has_null_failed_test(tmp_path):
    m, _, db, _ = await _build(tmp_path)
    await _seed_run(db, results=[_res("pri_sec", "Primary to Secondary", 0.1)], result="PASS")
    await _finish(m, result="PASS")
    (row,) = _rows(tmp_path)
    assert row["result"] == "Pass" and row["failed_test"] is None
    await db.close()


async def test_disabled_module_writes_nothing(tmp_path):
    m, _, db, _ = await _build(tmp_path, enabled=False)
    await _seed_run(db)
    await _finish(m)
    assert _rows(tmp_path) == []
    await db.close()


async def test_a_run_without_a_serial_is_skipped_with_a_warning(tmp_path):
    m, _, db, events = await _build(tmp_path)
    await _seed_run(db, serial="")
    await _finish(m)
    assert _rows(tmp_path) == [] and await m.alerts() == []
    assert any("no serial" in (e.get("message") or "") for e in events)
    await db.close()


# --- the run record is still being completed when run-finished arrives (seen live) -----------------------

async def _mid_flight(db, run_id="R1"):
    """The run record as the runs module has it a moment after the controller's last events: 2 of 3 results
    stored and the status still `running`, while all 3 `test-result` events have already been logged."""
    await db.repo.put("run", {"run_id": run_id, "status": "running", "serial_no": "SN-1", "recipe_id": "001",
                              "operator": "admin", "started_ts": _ts(18, 1, 29), "results": RESULTS[:2]},
                      id=run_id, summary="run")
    for r in RESULTS:
        await db.repo.put("run_event", {"type": "test-result", "run_id": run_id, **r}, summary="test-result")


async def test_the_last_test_still_being_stored_is_waited_for_not_written_as_null(tmp_path):
    m, _, db, _ = await _build(tmp_path)
    await _mid_flight(db)
    task = asyncio.create_task(_finish(m))                # run-finished arrives while the record is incomplete
    await asyncio.sleep(0.4)
    assert _rows(tmp_path) == []                          # it WAITS - no partial row is written
    await _seed_run(db)                                   # the runs module catches up: 3rd result + status finished
    await task
    (row,) = _rows(tmp_path)
    assert row["hv_sec_to_core_winding_actual"] == "0.31" and row["hv_sec_to_core_winding_result"] == "Pass"
    assert row["failed_test"] == "hv_pri_to_core_winding"
    await db.close()


async def test_a_record_that_never_completes_fails_loudly_and_writes_no_partial_row(tmp_path):
    m, _, db, events = await _build(tmp_path)
    m.complete_timeout_s = 0.3
    await _mid_flight(db)
    await _finish(m)
    assert _rows(tmp_path) == []
    (alert,) = await m.alerts()
    assert "2 of 3 test results stored" in alert["error"] and "nothing written" in alert["error"]
    await _seed_run(db)                                   # complete now -> Retry delivers the full row
    assert (await m.alert_retry("R1"))["ok"] is True
    (row,) = _rows(tmp_path)
    assert row["hv_sec_to_core_winding_actual"] == "0.31"
    await db.close()


async def test_preview_does_not_wait(tmp_path):
    m, _, db, _ = await _build(tmp_path, with_table=False)
    await _mid_flight(db)
    p = await m.preview("R1")                             # an admin looking at a running run: no 5 s wait, no error
    assert p["row"]["hv_pri_to_core_winding_actual"] == "12.5" and p["row"]["hv_sec_to_core_winding_actual"] is None
    await db.close()


# --- loud failure + retry -----------------------------------------------------------------------------

async def test_failure_is_recorded_loudly_then_retry_delivers(tmp_path):
    m, core, db, events = await _build(tmp_path, with_table=False)         # table missing -> the write fails
    await _seed_run(db)
    await _finish(m)
    (alert,) = await m.alerts()
    assert alert["serial"] == "SN-1" and alert["status"] == "failed" and alert["error"]
    assert any(e.get("level") == "error" and e.get("message") == "write to the Okaya table failed" for e in events)
    assert (await m.health()).status.name == "DEGRADED"
    assert (await m.alert_retry("R1"))["ok"] is False                      # still failing -> stays loud
    from modules.okaya_mes import writer
    writer.table_def("txr_testtable").create(m._eng())
    assert (await m.alert_retry("R1"))["ok"] is True
    assert await m.alerts() == [] and len(_rows(tmp_path)) == 1
    assert (await m.health()).status.name == "OK"
    await db.close()


async def test_dismiss_clears_the_alert_without_delivering(tmp_path):
    m, _, db, events = await _build(tmp_path, with_table=False)
    await _seed_run(db)
    await _finish(m)
    assert (await m.alert_dismiss("R1", by="alice"))["ok"] is True
    assert await m.alerts() == []
    assert any(e.get("level") == "warning" and "WITHOUT delivery" in (e.get("message") or "") for e in events)
    await db.close()


async def test_enabled_but_unconfigured_is_degraded_and_never_crashes(tmp_path):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, auth=TokenVerifier(), station="st1", diag=Diagnostics("st1", "0.0.0", sinks=[]))
    m = OkayaMes.construct(core, {"enabled": True})
    await m.init()
    assert (await m.health()).status.name == "DEGRADED" and m.problem() == "no database server configured"
    await _seed_run(db)
    await _finish(m)                                  # recorded as a loud failure, no exception
    assert len(await m.alerts()) == 1
    await db.close()


# --- settings / checks ---------------------------------------------------------------------------------

async def test_config_round_trip_redacts_and_keeps_the_stored_password(tmp_path):
    m, _, db, _ = await _build(tmp_path)
    await m.set_config({"connection": {"provider": "sqlserver", "host": "mes01", "user": "sa", "password": "s3cret"},
                        "database": "okaya", "table": "txr_testtable", "station_name": "HV Test Bench"})
    cfg = m.get_config()
    assert "password" not in cfg["connection"] and cfg["connection"]["has_password"] is True
    await m.set_config({"connection": {"provider": "sqlserver", "host": "mes01", "user": "sa", "password": ""}})
    assert m.connection["password"] == "s3cret"                          # blank = keep (same server)
    await m.set_config({"connection": {"provider": "sqlserver", "host": "OTHER", "user": "sa", "password": ""}})
    assert "password" not in m.connection                                # never re-sent to a different host
    m2 = OkayaMes.construct(m.core, {})
    await m2.init()
    assert m2.table == "txr_testtable" and m2.station_name == "HV Test Bench" and m2.enabled is True
    await db.close()


async def test_table_check_and_create(tmp_path):
    m, _, db, _ = await _build(tmp_path, with_table=False)
    chk = await m.check_table(None, None, None)
    assert chk["exists"] is False and chk["ok"] is False
    made = await m.create_table(None, None, None)
    assert made["ok"] is True and made["missing"] == []
    # a customer table with a missing column is reported by name, never silently padded
    con = sqlite3.connect(tmp_path / "okaya.sqlite")
    con.execute("CREATE TABLE short_table (date_time DATETIME, serial_no VARCHAR(50))")
    con.commit()
    con.close()
    short = await m.check_table(None, None, "short_table")
    assert short["ok"] is False and "model_name" in short["missing"] and "failed_test" in short["detail"]
    await db.close()


async def test_preview_shows_the_row_without_touching_the_database(tmp_path):
    m, _, db, _ = await _build(tmp_path, with_table=False)
    await _seed_run(db)
    p = await m.preview("R1")
    assert p["columns"] == list(rb.COLUMNS) and p["row"]["date_time"] == "2026-10-26 18:02:44"
    assert p["row"]["failed_test"] == "hv_pri_to_core_winding" and p["row"]["model_name"] == "001"
    await db.close()


# --- REST -----------------------------------------------------------------------------------------------

_PRINCIPALS = {
    "admin": Principal("alice", role="super_admin", permissions=frozenset({"SYSTEM.SETTINGS", "TEST.RUN"})),
    "operator": Principal("bob", role="operator", permissions=frozenset({"TEST.RUN"})),
    "viewer": Principal("v", role="viewer", permissions=frozenset({"REPORT.VIEW"})),
}


def _raise():
    raise AuthError("bad token")


@pytest.fixture
async def api(tmp_path):
    m, core, db, events = await _build(tmp_path, with_table=False)
    core.auth.register(lambda t: _PRINCIPALS[t] if t in _PRINCIPALS else _raise())
    app = FastAPI()
    app.state.auth = core.auth
    app.include_router(m.router)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, m, db
    await db.close()


def _h(who):
    return {"Authorization": f"Bearer {who}"}


async def test_rest_settings_are_admin_only_and_never_return_the_password(api):
    c, m, _ = api
    await m.set_config({"connection": {"provider": "sqlserver", "host": "h", "user": "u", "password": "pw"}})
    for method, path in (("get", "/okaya-mes/status"), ("get", "/okaya-mes/config")):
        assert (await getattr(c, method)(path, headers=_h("operator"))).status_code == 403
        assert (await getattr(c, method)(path, headers=_h("admin"))).status_code == 200
    assert "pw" not in (await c.get("/okaya-mes/config", headers=_h("admin"))).text
    assert (await c.put("/okaya-mes/config", json={"enabled": False}, headers=_h("operator"))).status_code == 403
    assert (await c.post("/okaya-mes/table/create", json={}, headers=_h("operator"))).status_code == 403


async def test_rest_check_create_preview_and_alerts(api):
    c, m, db = api
    assert (await c.post("/okaya-mes/table/check", json={}, headers=_h("admin"))).json()["exists"] is False
    assert (await c.post("/okaya-mes/table/create", json={}, headers=_h("admin"))).json()["ok"] is True
    assert (await c.post("/okaya-mes/db/test", json={}, headers=_h("admin"))).json()["ok"] is True
    await _seed_run(db)
    assert (await c.get("/okaya-mes/preview/R1", headers=_h("admin"))).json()["row"]["serial_no"] == "SN-1"
    assert (await c.get("/okaya-mes/preview/NOPE", headers=_h("admin"))).status_code == 404
    # alerts: operators may list / retry / dismiss, viewers may not
    await m._record_failure("R9", "SN-9", "FAIL", RuntimeError("boom"))
    assert (await c.get("/okaya-mes/alerts", headers=_h("viewer"))).status_code == 403
    items = (await c.get("/okaya-mes/alerts", headers=_h("operator"))).json()
    assert items["count"] == 1 and items["items"][0]["error"] == "boom"
    assert (await c.post("/okaya-mes/alerts/R9/dismiss", headers=_h("operator"))).json()["ok"] is True
    assert (await c.get("/okaya-mes/alerts", headers=_h("operator"))).json()["count"] == 0


async def test_send_run_backfills_even_while_disabled_and_is_admin_only(api):
    c, m, db = api
    m.enabled = False
    await c.post("/okaya-mes/table/create", json={}, headers=_h("admin"))
    await _seed_run(db)
    assert (await c.post("/okaya-mes/runs/R1/send", headers=_h("operator"))).status_code == 403
    ok = await c.post("/okaya-mes/runs/R1/send", headers=_h("admin"))
    assert ok.status_code == 200 and ok.json()["failed_test"] == "hv_pri_to_core_winding"
    assert (await c.post("/okaya-mes/runs/NOPE/send", headers=_h("admin"))).status_code == 422
    assert len(_rows(m.connection["path"] and __import__("pathlib").Path(m.connection["path"]).parent)) == 1

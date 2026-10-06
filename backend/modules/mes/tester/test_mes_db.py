"""MES database transport — inbound status lookup, outbound one-table write, loud failure, discovery.

sqlite files stand in for the customer's MySQL / SQL Server (SQLAlchemy Core is dialect-agnostic; the
dialect-specific listing SQL is asserted at string level in core/services dbconn tests and verified by
the user on the real servers).
"""

import datetime as dt
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import create_engine, inspect

from core.framework.contract import CoreServices
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from core.services.interlock import InterlockPort
from modules.mes.variants.default import DefaultMes


# --- helpers ---------------------------------------------------------------------------------

def _sqlite_conn(path) -> dict:
    return {"provider": "sqlite", "path": str(path)}


def _make_source(path, rows):
    """A customer-style MES table: serial / status plus date + time kept in SEPARATE columns."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE mes_status (serial TEXT, status TEXT, d TEXT, t TEXT)")
    con.executemany("INSERT INTO mes_status VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()


def _inbound(path, **kw) -> dict:
    return {"connection": _sqlite_conn(path), "table": "mes_status", "serial_column": "serial",
            "status_column": "status", "allow_value": "PASS", **kw}


async def _build(tmp_path, *, inbound=None, outbound=None, gate=True, publish=True, provider="database",
                 on_error="block", on_missing="block"):
    db = Database(":memory:", station="st2", source_version="0.0.0")
    await db.connect()
    events: list[dict] = []
    core = CoreServices(db=db, interlock=InterlockPort(), auth=TokenVerifier(),
                        diag=Diagnostics("st2", "0.0.0", sinks=[events.append]), station="st2")
    cfg = {"stage": "st2", "provider": provider,
           "gate": {"enabled": gate, "on_missing": on_missing, "on_error": on_error},
           "publish": {"enabled": publish},
           "database": {"inbound": inbound or {}, "outbound": outbound or {}}}
    module = DefaultMes.construct(core, cfg)
    await module.init()
    return module, core, db, events


@pytest.fixture
async def inb(tmp_path):
    """Gate against a table with history rows; latest_by is set per test."""
    src = tmp_path / "customer.sqlite"
    _make_source(src, [
        ("SN-PASS", "PASS", "2026-10-01", "08:00:00"),
        ("SN-FAIL", "FAIL", "2026-10-01", "08:00:00"),
        ("SN-LOWER", " pass ", "2026-10-01", "08:00:00"),
        ("SN-HIST1", "FAIL", "2026-10-01", "08:00:00"),      # older FAIL ...
        ("SN-HIST1", "PASS", "2026-10-01", "09:30:00"),      # ... then a newer PASS (same day)
        ("SN-HIST2", "PASS", "2026-10-02", "07:00:00"),      # older PASS ...
        ("SN-HIST2", "FAIL", "2026-10-02", "11:00:00"),      # ... then a newer FAIL
        ("SN-DAYS", "FAIL", "2026-10-03", "23:59:59"),
        ("SN-DAYS", "PASS", "2026-10-04", "00:00:01"),       # newer by DATE although earlier by time
    ])
    return src


# --- inbound ---------------------------------------------------------------------------------

async def test_inbound_allow_value_allows_anything_else_blocks(tmp_path, inb):
    m, *_ = await _build(tmp_path, inbound=_inbound(inb))
    ok = await m.check("SN-PASS", {})
    assert ok.allowed and ok.prior_result == "PASS"
    bad = await m.check("SN-FAIL", {})
    assert not bad.allowed and bad.prior_result == "FAIL" and "not 'PASS'" in bad.detail


async def test_inbound_compare_is_trimmed_and_case_insensitive_by_default(tmp_path, inb):
    m, *_ = await _build(tmp_path, inbound=_inbound(inb))
    assert (await m.check("SN-LOWER", {})).allowed
    strict, *_ = await _build(tmp_path, inbound=_inbound(inb, ignore_case=False))
    assert not (await strict.check("SN-LOWER", {})).allowed


async def test_inbound_missing_row_follows_on_missing(tmp_path, inb):
    block, *_ = await _build(tmp_path, inbound=_inbound(inb))
    assert not (await block.check("SN-NONE", {})).allowed
    allow, *_ = await _build(tmp_path, inbound=_inbound(inb), on_missing="allow")
    assert (await allow.check("SN-NONE", {})).allowed


async def test_inbound_history_without_latest_by_requires_every_row_to_allow(tmp_path, inb):
    m, *_ = await _build(tmp_path, inbound=_inbound(inb))
    res = await m.check("SN-HIST1", {})                  # FAIL then PASS -> fail-safe block
    assert not res.allowed and "2 rows matched" in res.detail


async def test_inbound_latest_by_single_column_newest_wins(tmp_path, inb):
    m, *_ = await _build(tmp_path, inbound=_inbound(inb, latest_by=["t"]))
    assert (await m.check("SN-HIST1", {})).allowed       # newest (09:30) is PASS
    assert not (await m.check("SN-HIST2", {})).allowed   # newest (11:00) is FAIL


async def test_inbound_latest_by_date_then_time_columns(tmp_path, inb):
    """Date and time in separate columns: [date, time] — the date decides first."""
    m, *_ = await _build(tmp_path, inbound=_inbound(inb, latest_by=["d", "t"]))
    assert (await m.check("SN-DAYS", {})).allowed        # 10-04 00:00:01 > 10-03 23:59:59
    wrong, *_ = await _build(tmp_path, inbound=_inbound(inb, latest_by=["t"]))
    assert not (await wrong.check("SN-DAYS", {})).allowed   # time alone picks the wrong row
    assert (await m.check("SN-HIST1", {})).allowed and not (await m.check("SN-HIST2", {})).allowed


async def test_inbound_db_error_blocks_loudly_and_policy_can_allow(tmp_path, inb):
    broken = _inbound(inb, table="no_such_table")
    m, _, _, events = await _build(tmp_path, inbound=broken)
    res = await m.check("SN-PASS", {})
    assert not res.allowed and "MES database error" in res.detail
    lenient, *_ = await _build(tmp_path, inbound=broken, on_error="allow")
    r2 = await lenient.check("SN-PASS", {})
    assert r2.allowed and "allowed by policy" in r2.detail


async def test_inbound_unconfigured_is_blocked_with_the_reason(tmp_path):
    m, *_ = await _build(tmp_path, inbound={})
    res = await m.check("SN1", {})
    assert not res.allowed and "not configured" in res.detail


async def test_inbound_is_read_only(tmp_path, inb):
    m, *_ = await _build(tmp_path, inbound=_inbound(inb))
    before = sqlite3.connect(inb).execute("SELECT COUNT(*) FROM mes_status").fetchone()[0]
    await m.check("SN-PASS", {})
    assert sqlite3.connect(inb).execute("SELECT COUNT(*) FROM mes_status").fetchone()[0] == before


async def test_inbound_manually_typed_names_work_without_listing(tmp_path, inb):
    """The query uses table()/column(), not reflection — hand-typed names (no listing permission) are fine."""
    m, *_ = await _build(tmp_path, inbound=_inbound(inb, table="mes_status", serial_column="serial"))
    assert (await m.check("SN-PASS", {})).allowed


async def test_gate_disabled_skips_the_database(tmp_path):
    m, *_ = await _build(tmp_path, inbound={}, gate=False)
    assert (await m.check("SN1", {})).allowed


# --- outbound --------------------------------------------------------------------------------

def _outbound(path, **kw) -> dict:
    return {"connection": _sqlite_conn(path), "table": "mes_results", **kw}


async def _seed_run(db, run_id="R1", serial="SN-1", result="PASS"):
    await db.repo.put("run", {"serial_no": serial, "result": result, "model": "INV", "operator": "op1",
                              "recipe_id": "inv-c", "recipe_version": 3,
                              "started_ts": dt.datetime(2026, 10, 5, 13, 0).timestamp(),
                              "finished_ts": dt.datetime(2026, 10, 5, 13, 2).timestamp()},
                      id=run_id)


async def _finish(m, run_id="R1", result="PASS"):
    await m._on_event("tmf/st2/event/run-finished",
                      {"type": "run-finished", "ts": 5.0, "payload": {"run_id": run_id, "result": result}})


def _rows(path, table="mes_results"):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]
    finally:
        con.close()


async def test_outbound_ensure_creates_table_with_report_header_schema(tmp_path):
    target = tmp_path / "out.sqlite"
    m, *_ = await _build(tmp_path, outbound=_outbound(target))
    out = await m.outbound_ensure(_outbound(target))
    assert out["ok"] and out["exists"] is True
    cols = [c["name"] for c in inspect(create_engine(f"sqlite:///{target}")).get_columns("mes_results")]
    assert cols == ["run_id", "station", "serial_no", "model", "operator", "recipe_id", "recipe_version",
                    "result", "started_ts", "finished_ts", "business_day", "shift_label", "created_at"]


async def test_outbound_run_finished_writes_one_row_instantly(tmp_path):
    target = tmp_path / "out.sqlite"
    m, _, db, events = await _build(tmp_path, outbound=_outbound(target))
    await m.outbound_ensure(_outbound(target))
    await _seed_run(db)
    await _finish(m)
    (row,) = _rows(target)
    assert (row["run_id"], row["serial_no"], row["result"], row["model"], row["operator"]) == \
        ("R1", "SN-1", "PASS", "INV", "op1")
    assert row["station"] == "st2" and row["recipe_version"] == 3 and row["business_day"] == "2026-10-05"
    assert row["finished_ts"] > row["started_ts"] and row["created_at"] == row["finished_ts"]
    assert not any(e["level"] == "error" for e in events)
    assert await m.alerts() == []


async def test_outbound_is_idempotent_per_run(tmp_path):
    target = tmp_path / "out.sqlite"
    m, _, db, _ = await _build(tmp_path, outbound=_outbound(target))
    await m.outbound_ensure(_outbound(target))
    await _seed_run(db)
    await _finish(m, result="FAIL")
    await _finish(m, result="PASS")                      # same run re-sent -> replaced, never duplicated
    (row,) = _rows(target)
    assert row["result"] == "PASS"


async def test_outbound_existing_customer_table_with_mapping_and_datetime_columns(tmp_path):
    target = tmp_path / "cust.sqlite"
    con = sqlite3.connect(target)
    con.execute("CREATE TABLE prod_log (RunKey TEXT, Barcode TEXT, Verdict TEXT, FinishedAt DATETIME, "
                "Day DATE, Note TEXT)")
    con.commit(); con.close()                                         # noqa: E702
    cmap = {"run_id": "RunKey", "serial_no": "Barcode", "result": "Verdict",
            "finished_ts": "FinishedAt", "business_day": "Day"}
    ob = _outbound(target, table="prod_log", column_map=cmap)
    m, _, db, _ = await _build(tmp_path, outbound=ob)
    v = await m.outbound_validate(ob)
    assert v["ok"] and v["exists"] and not v["missing"]
    await _seed_run(db)
    await _finish(m)
    (row,) = _rows(target, "prod_log")
    assert (row["RunKey"], row["Barcode"], row["Verdict"]) == ("R1", "SN-1", "PASS")
    assert row["FinishedAt"].startswith("2026-10-05 13:02") and row["Day"] == "2026-10-05"
    assert row["Note"] is None                                       # unmapped column left alone


async def test_outbound_validate_reports_missing_unmapped_and_blocking(tmp_path):
    target = tmp_path / "cust.sqlite"
    con = sqlite3.connect(target)
    con.execute("CREATE TABLE t (a TEXT, b TEXT NOT NULL)")
    con.commit(); con.close()                                         # noqa: E702
    m, *_ = await _build(tmp_path)
    v = await m.outbound_validate(_outbound(target, table="t", column_map={"run_id": "a", "result": "zz"}))
    assert not v["ok"]
    assert v["unmapped_required"] == ["serial_no"]
    assert v["missing"] == [{"field": "result", "column": "zz"}]
    assert v["blocking"] == ["b"]                                     # would make every INSERT fail
    assert "serial_no" in v["detail"] and "zz" in v["detail"] and "b" in v["detail"]


async def test_outbound_add_missing_columns(tmp_path):
    target = tmp_path / "cust.sqlite"
    con = sqlite3.connect(target)
    con.execute("CREATE TABLE t (run_id TEXT, serial_no TEXT, result TEXT)")
    con.commit(); con.close()                                         # noqa: E702
    ob = _outbound(target, table="t", column_map={"run_id": "run_id", "serial_no": "serial_no",
                                                  "result": "result", "model": "model"})
    m, *_ = await _build(tmp_path, outbound=ob)
    assert (await m.outbound_validate(ob))["missing"] == [{"field": "model", "column": "model"}]
    done = await m.outbound_ensure(ob, add_missing=True)
    assert done["ok"] and not done["missing"]
    assert "model" in [c["name"] for c in inspect(create_engine(f"sqlite:///{target}")).get_columns("t")]


async def test_outbound_ensure_rejects_unsafe_names(tmp_path):
    m, *_ = await _build(tmp_path)
    out = await m.outbound_ensure(_outbound(tmp_path / "o.sqlite", table="x; DROP TABLE y"))
    assert out["ok"] is False and "letters, digits" in out["detail"]


# --- outbound failure: loud, no outbox -----------------------------------------------------------

async def test_outbound_failure_is_recorded_alerted_and_retryable(tmp_path):
    target = tmp_path / "out.sqlite"                      # table NOT created -> the write fails
    m, core, db, events = await _build(tmp_path, outbound=_outbound(target))
    await _seed_run(db)
    await _finish(m)
    errs = [e for e in events if e["level"] == "error" and e["subsystem"] == "mes"]
    assert errs and errs[0]["context"]["serial"] == "SN-1" and errs[0]["context"]["run_id"] == "R1"
    (alert,) = await m.alerts()
    assert alert["status"] == "failed" and alert["serial"] == "SN-1" and alert["error"]
    assert (await m.health()).status.value == "degraded"
    assert (await m.status())["failed_pushes"] == 1
    # nothing queued anywhere: only the status record exists, and no payload copy
    assert set(alert) == {"run_id", "serial", "result", "status", "error", "ts"}

    retry = await m.alert_retry("R1")                     # still failing -> stays loud
    assert retry["ok"] is False and await m.alerts()

    await m.outbound_ensure(_outbound(target))            # operator fixes the cause ...
    retry = await m.alert_retry("R1")                     # ... and retries: row rebuilt from the run record
    assert retry["ok"] is True and await m.alerts() == []
    assert _rows(target)[0]["serial_no"] == "SN-1"
    assert (await m.health()).status.value == "ok"


async def test_outbound_dismiss_is_audited(tmp_path):
    m, _, db, events = await _build(tmp_path, outbound=_outbound(tmp_path / "out.sqlite"))
    await _seed_run(db)
    await _finish(m)
    await m.alert_dismiss("R1", by="alice")
    assert await m.alerts() == []
    audit = [e for e in events if "dismissed" in e["message"]]
    assert audit and audit[0]["context"]["by"] == "alice" and audit[0]["context"]["error"]


async def test_success_after_failure_clears_the_alert(tmp_path):
    target = tmp_path / "out.sqlite"
    m, _, db, _ = await _build(tmp_path, outbound=_outbound(target))
    await _seed_run(db)
    await _finish(m)
    assert await m.alerts()
    await m.outbound_ensure(_outbound(target))
    await _finish(m)                                      # a later finish event for the same run delivers
    assert await m.alerts() == []


async def test_publish_disabled_sends_nothing_and_never_alerts(tmp_path):
    m, _, db, events = await _build(tmp_path, outbound=_outbound(tmp_path / "out.sqlite"), publish=False)
    await _seed_run(db)
    await _finish(m)
    assert await m.alerts() == [] and not any(e["level"] == "error" for e in events)


async def test_folder_publish_failure_is_loud_too(tmp_path, monkeypatch):
    """The loud path is transport-independent: a folder write error alerts the same way."""
    m, _, db, _ = await _build(tmp_path, provider="folder")
    async def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(m.provider, "publish_result", boom)
    await _seed_run(db)
    await _finish(m)
    (alert,) = await m.alerts()
    assert "disk full" in alert["error"]


# --- settings: runtime provider switch, redaction, password keep ----------------------------------

async def test_set_config_switches_provider_and_persists(tmp_path, inb):
    m, _, db, _ = await _build(tmp_path, provider="folder", inbound=_inbound(inb))
    assert m.provider.describe()["kind"] == "folder"
    st = await m.set_config(provider="database", on_error="allow")
    assert st["provider"] == "database" and st["on_error"] == "allow"
    assert st["provider_detail"]["kind"] == "database" and st["provider_detail"]["inbound"]["ready"]
    rec = (await db.repo.get("mes_setting", "mes"))["data"]
    assert rec["provider"] == "database" and rec["on_error"] == "allow"
    with pytest.raises(ValueError):
        await m.set_config(provider="carrier-pigeon")
    with pytest.raises(ValueError):
        await m.set_config(on_missing="maybe")


async def test_provider_choice_survives_restart(tmp_path):
    m, core, db, _ = await _build(tmp_path, provider="folder")
    await m.set_config(provider="database")
    m2 = DefaultMes.construct(core, {"provider": "folder"})
    await m2.init()
    assert m2.provider_kind == "database"


async def test_db_config_is_redacted_and_blank_password_keeps_the_stored_one(tmp_path):
    m, _, db, _ = await _build(tmp_path)
    conn = {"provider": "mysql", "host": "h1", "user": "u", "password": "s3cret", "port": 3306}
    await m.set_db_config({"inbound": {"connection": conn, "table": "t"}})
    shown = m.get_db_config()
    assert "password" not in shown["inbound"]["connection"] and shown["inbound"]["connection"]["has_password"]
    # editing another field with a blank password keeps the secret
    await m.set_db_config({"inbound": {"connection": {**conn, "password": "", "has_password": True}}})
    assert m.db_config["inbound"]["connection"]["password"] == "s3cret"
    # ... but pointing at a DIFFERENT host must never re-use it
    await m.set_db_config({"inbound": {"connection": {**conn, "host": "evil", "password": ""}}})
    assert "password" not in m.db_config["inbound"]["connection"]
    assert (await db.repo.get("mes_db_config", "mes_db")) is not None


async def test_stored_password_is_only_used_for_the_same_server_in_helpers(tmp_path):
    m, *_ = await _build(tmp_path)
    await m.set_db_config({"inbound": {"connection": {"provider": "mysql", "host": "h1", "user": "u",
                                                      "password": "s3cret"}}})
    same = m._conn("inbound", {"provider": "mysql", "host": "h1", "user": "u"})
    other = m._conn("inbound", {"provider": "mysql", "host": "h2", "user": "u"})
    assert same["password"] == "s3cret" and not other.get("password")


async def test_same_as_inbound_uses_the_inbound_connection(tmp_path, inb):
    m, *_ = await _build(tmp_path, inbound=_inbound(inb))
    ob = m._outbound({"same_as_inbound": True, "table": "x"})
    assert ob.cfg["connection"] == _sqlite_conn(inb)


# --- discovery (the configuration "process") -------------------------------------------------------

async def test_listing_databases_tables_columns_values(tmp_path, inb):
    m, *_ = await _build(tmp_path)
    c = _sqlite_conn(inb)
    assert (await m.db_test("inbound", c))["ok"]
    dbs = await m.db_databases("inbound", c)
    assert dbs["ok"] and dbs["items"] == ["customer"]
    tables = await m.db_tables("inbound", c, None)
    assert tables["ok"] and tables["items"] == ["mes_status"]
    cols = await m.db_columns("inbound", c, None, "mes_status")
    assert [x["name"] for x in cols["items"]] == ["serial", "status", "d", "t"]
    vals = await m.db_values(c, None, "mes_status", "status")
    assert vals["ok"] and set(vals["items"]) == {"PASS", "FAIL", " pass "}


async def test_views_are_listed_as_tables(tmp_path, inb):
    con = sqlite3.connect(inb)
    con.execute("CREATE VIEW v_mes AS SELECT serial, status FROM mes_status")
    con.commit(); con.close()                                         # noqa: E702
    m, *_ = await _build(tmp_path)
    assert "v_mes" in (await m.db_tables("inbound", _sqlite_conn(inb), None))["items"]


async def test_listing_failure_degrades_to_manual_entry_instead_of_erroring(tmp_path):
    m, *_ = await _build(tmp_path)
    bad = {"provider": "sqlite", "path": str(tmp_path / "no" / "such" / "dir" / "x.sqlite")}
    for res in (await m.db_tables("inbound", bad, None),
                await m.db_columns("inbound", bad, None, "t"),
                await m.db_values(bad, None, "t", "c")):
        assert res["ok"] is False and res["items"] == [] and res["detail"]
    assert (await m.db_test("inbound", bad))["ok"] is False


async def test_verify_confirms_manually_typed_names(tmp_path, inb):
    m, *_ = await _build(tmp_path)
    c = _sqlite_conn(inb)
    assert (await m.db_verify("inbound", c, None, "mes_status", ["serial", "status"]))["ok"]
    bad = await m.db_verify("inbound", c, None, "mes_status", ["serial", "nope"])
    assert bad["ok"] is False and "nope" in bad["detail"]
    assert (await m.db_verify("inbound", c, None, "", ["a"]))["ok"] is False


async def test_inbound_dry_run_shows_rows_and_decision(tmp_path, inb):
    m, *_ = await _build(tmp_path)
    draft = _inbound(inb, latest_by=["d", "t"])
    res = await m.inbound_check("SN-DAYS", draft)
    assert res["allowed"] and res["rows"] == ["PASS"]             # latest_by limits to the newest row
    assert (await m.inbound_check("SN-FAIL", draft))["allowed"] is False
    assert (await m.inbound_check("SN-X", draft))["matched"] == 0


# --- REST ------------------------------------------------------------------------------------------

_PRINCIPALS = {
    "admin": Principal("alice", role="super_admin", permissions=frozenset({"SYSTEM.SETTINGS", "TEST.RUN"})),
    "operator": Principal("bob", role="operator", permissions=frozenset({"TEST.RUN"})),
    "viewer": Principal("v", role="viewer", permissions=frozenset({"REPORT.VIEW"})),
}


def _raise():
    raise AuthError("bad token")


@pytest.fixture
async def api(tmp_path, inb):
    m, core, db, events = await _build(tmp_path, inbound=_inbound(inb),
                                       outbound=_outbound(tmp_path / "out.sqlite"))
    core.auth.register(lambda t: _PRINCIPALS[t] if t in _PRINCIPALS else _raise())
    app = FastAPI()
    app.state.auth = core.auth
    app.include_router(m.router)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, m, db, events, tmp_path
    await db.close()


def _h(who):
    return {"Authorization": f"Bearer {who}"}


async def test_rest_settings_are_admin_only(api):
    c, *_ = api
    for method, path in (("get", "/mes/status"), ("get", "/mes/db-config")):
        assert (await getattr(c, method)(path, headers=_h("operator"))).status_code == 403
        assert (await getattr(c, method)(path, headers=_h("admin"))).status_code == 200
    r = await c.post("/mes/db/tables", json={"connection": {}}, headers=_h("operator"))
    assert r.status_code == 403


async def test_rest_config_validation_and_redaction(api):
    c, *_ = api
    bad = await c.put("/mes/config", json={"provider": "xml"}, headers=_h("admin"))
    assert bad.status_code == 422
    ok = await c.put("/mes/config", json={"provider": "database", "gate_enabled": True}, headers=_h("admin"))
    assert ok.status_code == 200 and ok.json()["provider"] == "database"
    cfg = (await c.get("/mes/db-config", headers=_h("admin"))).json()
    assert cfg["fields"][0]["name"] == "run_id" and cfg["inbound"]["table"] == "mes_status"


async def test_rest_process_endpoints(api):
    c, m, _, _, tmp = api
    conn = _sqlite_conn(tmp / "customer.sqlite")
    t = (await c.post("/mes/db/tables", json={"side": "inbound", "connection": conn}, headers=_h("admin"))).json()
    assert t["ok"] and "mes_status" in t["items"]
    chk = await c.post("/mes/db/inbound/check", json={"serial": "SN-PASS"}, headers=_h("admin"))
    assert chk.json()["allowed"] is True
    assert (await c.post("/mes/db/inbound/check", json={"serial": " "}, headers=_h("admin"))).status_code == 422
    assert (await c.post("/mes/db/test", json={"side": "sideways"}, headers=_h("admin"))).status_code == 422
    ens = await c.post("/mes/db/outbound/ensure", json={"outbound": _outbound(tmp / "out.sqlite")},
                       headers=_h("admin"))
    assert ens.json()["ok"] is True


async def test_rest_alerts_for_operators(api):
    c, m, db, _, tmp = api
    await _seed_run(db)
    await _finish(m)                                      # outbound table missing -> alert
    assert (await c.get("/mes/alerts", headers=_h("viewer"))).status_code == 403
    items = (await c.get("/mes/alerts", headers=_h("operator"))).json()
    assert items["count"] == 1 and items["items"][0]["serial"] == "SN-1"
    bad = await c.post("/mes/alerts/R1/retry", headers=_h("operator"))
    assert bad.json()["ok"] is False
    await m.outbound_ensure(_outbound(tmp / "out.sqlite"))
    assert (await c.post("/mes/alerts/R1/retry", headers=_h("operator"))).json()["ok"] is True
    assert (await c.get("/mes/alerts", headers=_h("operator"))).json()["count"] == 0


# --- runs -> interlock integration (HTTP 409 when MES blocks) --------------------------------------

async def test_runs_start_is_blocked_with_409_by_the_database_gate(tmp_path, inb):
    from modules.runs.variants.default import DefaultRuns

    class FakeBridge:
        online, station = True, "st2"
        async def request(self, op, args, *, station=None, timeout=None):
            return {"id": "x", "ok": True, "result": {}}

    class FakeConfig:
        async def resolve_recipe_from_barcode(self, barcode):
            return {"ok": True, "recipe_id": "inv", "parts": {"model": "inv"}}

    mes, core, db, _ = await _build(tmp_path, inbound=_inbound(inb, latest_by=["d", "t"]))
    runs_core = CoreServices(db=db, bridge=FakeBridge(), interlock=core.interlock,
                             diag=core.diag, station="st2", get_contract=lambda n: {"config": FakeConfig()}[n])
    runs = DefaultRuns.construct(runs_core, {})
    app = FastAPI()
    app.include_router(runs.router)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        blocked = await c.post("/runs/start", json={"barcode": "SN-FAIL"})
        assert blocked.status_code == 409 and "FAIL" in blocked.text
        allowed = await c.post("/runs/start", json={"barcode": "SN-PASS"})
        assert allowed.status_code == 200
    await db.close()


# --- injection safety --------------------------------------------------------------------------------

async def test_serial_with_sql_is_just_a_value(tmp_path, inb):
    """A serial containing SQL is just a value (parameterised) — it matches nothing and breaks nothing."""
    m, *_ = await _build(tmp_path, inbound=_inbound(inb))
    res = await m.check("x' OR '1'='1", {})
    assert not res.allowed and "no MES record" in res.detail
    assert sqlite3.connect(inb).execute("SELECT COUNT(*) FROM mes_status").fetchone()[0] == 9

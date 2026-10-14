"""D4 — report timestamps must be double precision.

`sqlalchemy.Float` with no precision is a 4-byte MySQL FLOAT (~7 significant digits): a 10-digit
epoch like 1760000000.123 is rounded by minutes. The schema must use Double; existing MySQL
databases are widened in place; already-rounded rows are repaired once from the runs records.
Real-MySQL assertions run when TMF_TEST_MYSQL_URL is set (CI job `report-mysql`)."""

import os
import struct

import pytest
from sqlalchemy import Float, create_engine, text
from sqlalchemy.dialects import mysql

from modules.report.store import ReportStore
from modules.report.store import store as store_mod
from modules.report.store.schema import metadata, report

TS = 1760000000.123456


def _f32(x: float) -> float:
    return struct.unpack("f", struct.pack("f", x))[0]


def test_schema_has_no_single_precision_float():
    """Guard for future schema modules: a bare Float() is FLOAT (4 bytes) on MySQL."""
    bad = [f"{t.name}.{c.name}" for t in metadata.tables.values() for c in t.columns
           if type(c.type) is Float]
    assert not bad, f"single-precision Float columns (use Double): {bad}"


@pytest.fixture
async def store(tmp_path):
    s = ReportStore()
    s.configure({"provider": "sqlite", "path": str(tmp_path / "r.sqlite")})
    await s.ensure_schema()
    yield s
    s.dispose()


def _rep(run_id, started=TS, finished=TS + 12.5, rows=None):
    return {"run_id": run_id, "station": "st1", "serial_no": run_id, "model": "M", "result": "PASS",
            "started_ts": started, "finished_ts": finished, "business_day": "2026-10-01",
            "rows": rows or [{"test_name": "T", "result": "PASS", "cycle_time_ms": 1234.5678}]}


async def test_epoch_timestamps_round_trip_exactly(store):
    await store.write(_rep("R1"))
    got = await store.get_report("R1")
    assert got["started_ts"] == TS and got["finished_ts"] == TS + 12.5 and got["created_at"] == TS + 12.5
    assert got["rows"][0]["cycle_time_ms"] == 1234.5678


# -- migration planning (pure) -----------------------------------------------------------------

def test_plan_widens_only_our_float_columns():
    reflected = {
        "tmf_report": [{"name": "started_ts", "type": mysql.FLOAT()},
                       {"name": "finished_ts", "type": mysql.DOUBLE()},      # already wide
                       {"name": "created_at", "type": mysql.FLOAT()},
                       {"name": "station", "type": mysql.VARCHAR(64)},
                       {"name": "foreign_float", "type": mysql.FLOAT()}],    # not ours
        "tmf_report_result": [{"name": "cycle_time_ms", "type": mysql.FLOAT()}],
    }
    assert store_mod.float_columns_to_widen(reflected) == [
        ("tmf_report", "started_ts"), ("tmf_report", "created_at"), ("tmf_report_result", "cycle_time_ms")]


def test_widen_ddl_is_modify_column_double_null():
    ddl = store_mod.widen_ddl(mysql.dialect(), [("tmf_report", "started_ts")])
    assert ddl == ["ALTER TABLE `tmf_report` MODIFY COLUMN `started_ts` DOUBLE NULL"]


async def test_widen_is_a_noop_off_mysql(store):
    assert store._engine.dialect.name == "sqlite"
    assert store.widen_float_columns() == []


# -- repair ------------------------------------------------------------------------------------

async def _rounded(store, run_id, started, finished):
    """Simulate a pre-fix MySQL row: single-precision-rounded timestamps."""
    await store.write(_rep(run_id, started, finished))
    with store._engine.begin() as c:
        c.execute(report.update().where(report.c.run_id == run_id).values(
            started_ts=_f32(started), finished_ts=_f32(finished), created_at=_f32(finished)))


async def test_repair_restores_full_precision_from_run_records(store):
    await _rounded(store, "R1", TS, TS + 12.5)
    assert (await store.get_report("R1"))["started_ts"] != TS            # damaged
    n = await store.repair_timestamps([{"run_id": "R1", "started_ts": TS, "finished_ts": TS + 12.5}])
    assert n == 1
    got = await store.get_report("R1")
    assert got["started_ts"] == TS and got["finished_ts"] == TS + 12.5 and got["created_at"] == TS + 12.5
    # idempotent: nothing left to fix
    assert await store.repair_timestamps([{"run_id": "R1", "started_ts": TS, "finished_ts": TS + 12.5}]) == 0


async def test_repair_leaves_unrelated_and_far_off_rows_alone(store):
    await store.write(_rep("FAR", 1_000_000_000.0, 1_000_000_010.0))      # >5000 s from the "truth"
    await store.write(_rep("NOREC"))                                      # no run record at all
    n = await store.repair_timestamps([
        {"run_id": "FAR", "started_ts": TS, "finished_ts": TS + 12.5},
        {"run_id": "GONE", "started_ts": TS, "finished_ts": TS},          # no report row
        {"run_id": "NOREC", "started_ts": None, "finished_ts": None}])
    assert n == 0
    assert (await store.get_report("FAR"))["started_ts"] == 1_000_000_000.0
    assert (await store.get_report("NOREC"))["started_ts"] == TS


# -- real MySQL / MariaDB (CI job report-mysql) --------------------------------------------------

MYSQL_URL = os.environ.get("TMF_TEST_MYSQL_URL")
needs_mysql = pytest.mark.skipif(not MYSQL_URL, reason="set TMF_TEST_MYSQL_URL to run against a real MySQL/MariaDB")

_OLD_DDL = [
    "DROP TABLE IF EXISTS tmf_report_result", "DROP TABLE IF EXISTS tmf_report",
    """CREATE TABLE tmf_report (run_id VARCHAR(64) PRIMARY KEY, station VARCHAR(64), serial_no VARCHAR(128),
       model VARCHAR(128), operator VARCHAR(128), recipe_id VARCHAR(128), recipe_version INT,
       result VARCHAR(32), started_ts FLOAT, finished_ts FLOAT, business_day VARCHAR(10),
       shift_label VARCHAR(64), created_at FLOAT)""",
    """CREATE TABLE tmf_report_result (id BIGINT AUTO_INCREMENT PRIMARY KEY, run_id VARCHAR(64), seq INT,
       test_name VARCHAR(255), test_group VARCHAR(128), expected VARCHAR(255), measured VARCHAR(255),
       result VARCHAR(32), unit VARCHAR(64), cycle_time_ms FLOAT,
       FOREIGN KEY (run_id) REFERENCES tmf_report(run_id) ON DELETE CASCADE)""",
]


def _col_types(eng):
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name IN ('tmf_report','tmf_report_result') "
            "AND data_type IN ('float','double')")).all()
    return {(t.lower(), n.lower()): d.lower() for t, n, d in rows}


def _cfg_from_url(url: str) -> dict:
    from sqlalchemy.engine import make_url
    u = make_url(url)
    return {"host": u.host, "port": u.port, "user": u.username, "password": u.password,
            "database": u.database}


@needs_mysql
async def test_mysql_old_float_ddl_is_widened_and_epoch_round_trips():
    raw = create_engine(MYSQL_URL)
    with raw.begin() as c:
        for stmt in _OLD_DDL:
            c.execute(text(stmt))
    assert set(_col_types(raw).values()) == {"float"}                      # the pre-fix shape
    s = ReportStore()
    s.configure({"provider": "mysql", **_cfg_from_url(MYSQL_URL)})
    try:
        await s.ensure_schema()                                            # create_all + widen
        assert set(_col_types(raw).values()) == {"double"}
        await s.ensure_schema()                                            # idempotent
        await s.write(_rep("R1"))
        got = await s.get_report("R1")
        assert got["started_ts"] == TS and got["rows"][0]["cycle_time_ms"] == 1234.5678
    finally:
        s.dispose()
        raw.dispose()


# -- module: one-time repair behind a marker --------------------------------------------------

async def _mod(tmp_path):
    from core.framework.contract import CoreServices
    from core.services.db import Database
    from core.services.diagnostics import Diagnostics
    from modules.report.variants.standard import StandardReport
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    mod = StandardReport.construct(core, {"outbox_path": str(tmp_path / "ob.sqlite")})
    await mod.outbox.connect()
    await mod.set_db_config({"provider": "sqlite", "path": str(tmp_path / "r.sqlite")})
    return mod, db


async def test_repair_runs_once_on_mysql_and_sets_marker(tmp_path, monkeypatch):
    mod, db = await _mod(tmp_path)
    try:
        await mod._repair_task                                   # drain the auto-scheduled run
        await db.repo.delete("config", 1e12)                     # forget it (and the db config)
        await mod.set_db_config({"provider": "sqlite", "path": str(tmp_path / "r.sqlite")})
        await mod._repair_task
        await db.repo.delete_id("config", "report_ts_repair")
        monkeypatch.setattr(type(mod.store), "dialect", property(lambda self: "mysql"))
        await _rounded(mod.store, "R1", TS, TS + 12.5)
        await db.repo.put("run", {"run_id": "R1", "started_ts": TS, "finished_ts": TS + 12.5}, id="R1")
        await mod._repair_timestamps_once()
        got = await mod.store.get_report("R1")
        assert got["started_ts"] == TS and got["finished_ts"] == TS + 12.5
        marker = await db.repo.get("config", "report_ts_repair")
        assert marker["data"]["done"] is True and marker["data"]["fixed"] == 1
        # marker present -> a damaged row added later is NOT rescanned
        await _rounded(mod.store, "R2", TS, TS + 1)
        await db.repo.put("run", {"run_id": "R2", "started_ts": TS, "finished_ts": TS + 1}, id="R2")
        await mod._repair_timestamps_once()
        assert (await mod.store.get_report("R2"))["started_ts"] != TS
    finally:
        await mod.outbox.close()
        mod.store.dispose()
        await db.close()


async def test_repair_failure_leaves_no_marker_so_next_boot_retries(tmp_path, monkeypatch):
    mod, db = await _mod(tmp_path)
    try:
        await mod._repair_task
        await db.repo.delete_id("config", "report_ts_repair")
        monkeypatch.setattr(type(mod.store), "dialect", property(lambda self: "mysql"))

        async def boom(_):
            raise RuntimeError("db down")
        monkeypatch.setattr(mod.store, "repair_timestamps", boom)
        await mod._repair_timestamps_once()                       # swallowed, never raises
        assert await db.repo.get("config", "report_ts_repair") is None
    finally:
        await mod.outbox.close()
        mod.store.dispose()
        await db.close()


async def test_non_mysql_sets_marker_without_scanning(tmp_path):
    mod, db = await _mod(tmp_path)
    try:
        await mod._repair_task
        m = await db.repo.get("config", "report_ts_repair")
        assert m["data"] == {"done": True, "fixed": 0, "dialect": "sqlite"}
    finally:
        await mod.outbox.close()
        mod.store.dispose()
        await db.close()

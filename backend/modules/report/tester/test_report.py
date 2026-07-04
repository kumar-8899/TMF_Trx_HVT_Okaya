"""report standalone tester — outbox spool + professional-DB store (on sqlite here).

Reports are assembled on run-finish, spooled to the local outbox, then forwarded to the
ReportStore (the pro DB; sqlite in tests). Queries/analytics read the store.
"""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

import modules.report  # noqa: F401 — registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.report.variants.standard import StandardReport


@pytest.fixture
async def ctx(tmp_path):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, auth=TokenVerifier(),
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    mod = StandardReport.construct(core, {"outbox_path": str(tmp_path / "outbox.sqlite")})
    await mod.outbox.connect()
    # configure the store to a local sqlite file (stands in for MySQL/SQL Server)
    await mod.set_db_config({"provider": "sqlite", "path": str(tmp_path / "reports.sqlite")})
    yield mod, core, db
    await mod.outbox.close()
    mod.store.dispose()
    await db.close()


async def _seed_run(db, run_id, result, recipe="inv-c", model="INV"):
    await db.repo.put("run", {"recipe_id": recipe, "recipe_version": 3, "model": model,
                              "serial_no": run_id, "operator": "op1", "started_ts": 1.0,
                              "finished_ts": 3.0, "result": result,
                              "results": [{"test_name": "OVP", "expected": "320", "measured": "319.4",
                                           "result": result, "cycle_time_ms": 412}]}, id=run_id)
    await db.repo.put("run_event", {"type": "run-started", "ts": 1.0, "run_id": run_id,
                                    "recipe": recipe, "version": 3})
    await db.repo.put("run_event", {"type": "run-finished", "ts": 3.0, "run_id": run_id, "result": result})


async def _finish(mod, db, run_id, result, recipe="inv-c", model="INV"):
    await _seed_run(db, run_id, result, recipe, model)
    await mod._on_event("tmf/st1/event/run-finished",
                        {"type": "run-finished", "ts": 3.0, "payload": {"run_id": run_id, "result": result}})
    await mod._drain()                                     # forward outbox -> store deterministically


def test_registered():
    rec = default_registry.get("report")
    assert rec.variant_ids == ["standard"]
    m = ManifestLoader().load("report")
    assert m.entitlement_key == "report" and m.contributes.api_prefix == "/reports"


async def test_spool_forward_and_read(ctx):
    mod, _, db = ctx
    await _finish(mod, db, "R1", "PASS")
    rep = await mod.get_report("R1")
    assert rep["result"] == "PASS" and rep["recipe_id"] == "inv-c" and rep["recipe_version"] == 3
    assert rep["started_ts"] == 1.0 and rep["finished_ts"] == 3.0
    assert rep["rows"][0]["test_name"] == "OVP"            # per-test child rows persisted


async def test_outbox_holds_when_db_unconfigured(tmp_path):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    mod = StandardReport.construct(core, {"outbox_path": str(tmp_path / "ob.sqlite")})
    await mod.outbox.connect()
    try:
        await _seed_run(db, "R1", "PASS")
        await mod._on_event("tmf/st1/event/run-finished",
                            {"type": "run-finished", "ts": 3.0, "payload": {"run_id": "R1", "result": "PASS"}})
        assert await mod.outbox.count() == 1               # store not configured -> spooled, not lost
        assert await mod._drain() == 0                     # nothing forwarded yet
        await mod.set_db_config({"provider": "sqlite", "path": str(tmp_path / "r.sqlite")})
        assert await mod._drain() == 1                     # config arrives -> drains
        assert await mod.outbox.count() == 0
        assert (await mod.get_report("R1"))["result"] == "PASS"
    finally:
        await mod.outbox.close(); mod.store.dispose(); await db.close()


async def test_list_and_analytics(ctx):
    mod, _, db = ctx
    await _finish(mod, db, "R1", "PASS", recipe="a", model="INV")
    await _finish(mod, db, "R2", "FAIL", recipe="a", model="INV")
    await _finish(mod, db, "R3", "PASS", recipe="b", model="DCX")
    assert (await mod.list_reports())["total"] == 3
    assert [r["run_id"] for r in (await mod.list_reports(result="FAIL"))["items"]] == ["R2"]
    a = await mod.analytics()
    assert a["total"] == 3 and a["passed"] == 2 and a["failed"] == 1


async def test_db_config_redacts_password(ctx):
    mod, _, _ = ctx
    await mod.set_db_config({"provider": "sqlite", "path": "x", "password": "secret"})
    cfg = await mod.get_db_config()
    assert cfg["configured"] and cfg["has_password"] is True and "password" not in cfg


async def test_db_config_test_endpoint(ctx, tmp_path):
    mod, _, _ = ctx
    ok = await mod.test_db_config({"provider": "sqlite", "path": str(tmp_path / "t.sqlite")})
    assert ok["ok"] and ok["status"] == "pass"


# --- REST ------------------------------------------------------------------

_PRINCIPALS = {
    "viewer": Principal("v", role="viewer", permissions=frozenset({"REPORT.VIEW"})),
    "exporter": Principal("e", role="engineer", permissions=frozenset({"REPORT.VIEW", "REPORT.EXPORT"})),
    "admin": Principal("a", role="super_admin", permissions=frozenset({"REPORT.VIEW", "REPORT.EXPORT", "SYSTEM.SETTINGS"})),
}


def _client(mod, core):
    core.auth.register(lambda t: _PRINCIPALS[t] if t in _PRINCIPALS else _raise())
    app = FastAPI()
    app.state.auth = core.auth
    app.include_router(mod.router, prefix="/reports")
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _raise():
    raise AuthError("bad token")


async def test_rest_and_db_config_gate(ctx):
    mod, core, db = ctx
    await _finish(mod, db, "R1", "PASS")
    async with _client(mod, core) as c:
        v = {"Authorization": "Bearer viewer"}
        assert (await c.get("/reports")).status_code == 401
        got = await c.get("/reports/R1", headers=v)
        assert got.status_code == 200 and got.json()["result"] == "PASS"
        assert (await c.get("/reports/none", headers=v)).status_code == 404
        assert (await c.get("/reports", headers=v)).json()["total"] == 1
        # db-config is super_admin only
        assert (await c.get("/reports/db-config", headers=v)).status_code == 403
        assert (await c.get("/reports/db-config", headers={"Authorization": "Bearer admin"})).status_code == 200


async def test_folder_mirror_still_works(tmp_path):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    root = tmp_path / "rep"
    mod = StandardReport.construct(core, {"outbox_path": str(tmp_path / "ob.sqlite"),
                                          "sinks": [{"type": "folder", "when": "all", "path": str(root), "format": "json"}]})
    await mod.outbox.connect()
    try:
        await _seed_run(db, "R1", "PASS")
        await mod._on_event("tmf/st1/event/run-finished",
                            {"type": "run-finished", "ts": 3.0, "payload": {"run_id": "R1", "result": "PASS"}})
        assert (root / "PASS" / "R1.json").exists()        # folder mirror independent of the store
    finally:
        await mod.outbox.close(); await db.close()


async def test_export_gated_and_formats(ctx):
    mod, core, db = ctx
    await _finish(mod, db, "R1", "PASS")
    async with _client(mod, core) as c:
        viewer = {"Authorization": "Bearer viewer"}
        exporter = {"Authorization": "Bearer exporter"}
        assert (await c.get("/reports/R1/export", headers=viewer)).status_code == 403
        j = await c.get("/reports/R1/export?format=json", headers=exporter)
        assert j.status_code == 200 and j.json()["run_id"] == "R1"
        csv = await c.get("/reports/R1/export?format=csv", headers=exporter)
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        assert (await c.get("/reports/none/export", headers=exporter)).status_code == 404

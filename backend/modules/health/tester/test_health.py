"""health standalone tester (CORE.md §6.2) — core + health, no bridge, :memory: db."""

import pytest

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.health.variants.default import DefaultHealth


@pytest.fixture
async def ctx(tmp_path):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, bridge=None,
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    module = DefaultHealth.construct(core, {"data_root": str(tmp_path), "disk_min_gb": 0.0})
    await module.init()
    yield module, core, db
    await db.close()


async def test_list_checks_and_reachability(ctx):
    module, _, _ = ctx
    checks = {c["id"]: c for c in module.list_checks()}
    assert "web.db_writable" in checks and "bridge.online" in checks
    assert checks["web.db_writable"]["reachable"] is True  # python executor


async def test_run_web_checks_pass(ctx):
    module, _, _ = ctx
    hid = await module.run(check_ids=["web.db_writable", "web.disk_space"])
    run = await module.get_run(hid)
    assert run["overall"] == "healthy"
    by = {v["check_id"]: v for v in run["verdicts"]}
    assert by["web.db_writable"]["status"] == "pass"
    assert by["web.disk_space"]["status"] == "pass"


async def test_bridge_check_unavailable_without_bridge(ctx):
    module, _, _ = ctx
    hid = await module.run(check_ids=["bridge.online"])
    run = await module.get_run(hid)
    by = {v["check_id"]: v for v in run["verdicts"]}
    assert by["bridge.online"]["status"] == "unavailable"
    # critical + unavailable -> we don't know it's healthy
    assert run["overall"] == "incomplete"


async def test_requires_dependency_skips(ctx):
    module, _, _ = ctx
    # bridge.roundtrip requires bridge.online, which is unavailable -> not passed -> skipped
    hid = await module.run(check_ids=["bridge.online", "bridge.roundtrip"])
    run = await module.get_run(hid)
    by = {v["check_id"]: v for v in run["verdicts"]}
    assert by["bridge.roundtrip"]["status"] == "skipped"
    assert "bridge.online" in by["bridge.roundtrip"]["summary"]


async def test_suite_and_current_and_unknown(ctx):
    module, _, _ = ctx
    assert any(s["name"] == "smoke" for s in module.list_suites())
    hid = await module.run(suite="smoke")
    cur = await module.current()
    assert cur["health_run_id"] == hid
    with pytest.raises(ValueError):
        await module.run(check_ids=["does.not.exist"])

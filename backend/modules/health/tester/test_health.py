"""health standalone tester (CORE.md §6.2) — core + health, no bridge, :memory: db."""

import time

import pytest

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.health.variants.default import DefaultHealth


class FakeBridge:
    """Minimal bridge for the seam: online flag + per-op request replies."""
    def __init__(self, online=True, replies=None):
        self._online = online
        self.connected = True
        self.replies = replies or {}

    @property
    def online(self):
        return self._online

    async def request(self, op, args, timeout=None):
        r = self.replies.get(op)
        return r(args) if callable(r) else (r if r is not None else {"ok": True})


async def _build(tmp_path, bridge=None):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, bridge=bridge,
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    module = DefaultHealth.construct(core, {"data_root": str(tmp_path), "disk_min_gb": 0.0})
    await module.init()
    return module, core, db


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


# --- R2: bridge seam (live + dispatched checks over a fake bridge) ---------


async def test_bridge_suite_live(tmp_path):
    bridge = FakeBridge(online=True, replies={
        "hello.echo": lambda a: {"ok": True, "ts": time.time()},
        "health.check.bridge.queue_depth": lambda a: {"ok": True, "status": "pass",
                                                       "summary": "queue ok", "data": {"depth": 2}},
    })
    module, _, db = await _build(tmp_path, bridge)
    try:
        hid = await module.run(suite="bridge")
        by = {v["check_id"]: v for v in (await module.get_run(hid))["verdicts"]}
        assert by["bridge.online"]["status"] == "pass"
        assert by["bridge.roundtrip"]["status"] == "pass"
        assert by["bridge.clock_skew"]["status"] == "pass"
        # dispatched to the LabVIEW handler (no local executor) -> verdict relayed
        assert by["bridge.queue_depth"]["status"] == "pass"
        assert by["bridge.queue_depth"]["data"] == {"depth": 2}
    finally:
        await db.close()


async def test_clock_skew_detects_skew(tmp_path):
    bridge = FakeBridge(online=True, replies={
        "hello.echo": lambda a: {"ok": True, "ts": time.time() - 60},  # 60s behind
    })
    module, _, db = await _build(tmp_path, bridge)
    try:
        hid = await module.run(check_ids=["bridge.online", "bridge.clock_skew"])
        by = {v["check_id"]: v for v in (await module.get_run(hid))["verdicts"]}
        assert by["bridge.clock_skew"]["status"] == "fail"
        assert by["bridge.clock_skew"]["data"]["skew_s"] >= 59
    finally:
        await db.close()


async def test_dispatched_check_unavailable_when_offline(tmp_path):
    bridge = FakeBridge(online=False)
    module, _, db = await _build(tmp_path, bridge)
    try:
        # queue_depth requires bridge.online (fails) -> skipped, not a false fail
        hid = await module.run(check_ids=["bridge.online", "bridge.queue_depth"])
        by = {v["check_id"]: v for v in (await module.get_run(hid))["verdicts"]}
        assert by["bridge.online"]["status"] == "fail"      # connected flag True, link offline
        assert by["bridge.queue_depth"]["status"] == "skipped"
    finally:
        await db.close()

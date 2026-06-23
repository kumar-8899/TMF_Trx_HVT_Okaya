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


async def _build(tmp_path, bridge=None, instances=None, disk_min_gb=0.0):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, bridge=bridge,
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    cfg = {"data_root": str(tmp_path), "disk_min_gb": disk_min_gb}
    if instances is not None:
        cfg["instances"] = instances
    module = DefaultHealth.construct(core, cfg)
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


async def test_trends_metrics(ctx):
    module, _, _ = ctx
    # disk check passes; force a failing web check via a tiny disk_min to vary results
    await module.run(check_ids=["web.db_writable"])              # pass
    module.config["disk_min_gb"] = 10 ** 9
    await module.run(check_ids=["web.disk_space"])               # fail
    await module.run(check_ids=["web.disk_space"])               # fail again
    t = await module.trends()
    assert t["runs_analyzed"] == 3
    disk = next(c for c in t["checks"] if c["check_id"] == "web.disk_space")
    assert disk["fails"] == 2 and disk["current_fail_streak"] == 2
    assert disk["mtbf_s"] is not None
    assert "web.disk_space" in t["repeated_failures"]


async def test_schedule_get_set(ctx):
    module, _, _ = ctx
    s = module.schedule_get()
    assert s["startup"] is False and s["suite"] == "smoke" and "smoke" in s["suites"]
    s2 = module.schedule_set({"every_30min": True, "daily": "06:30"})
    assert s2["every_30min"] is True and s2["daily"] == "06:30"


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


# --- R3: hardware checks, instance templating, maintenance gate ------------

INSTANCES = [{"id": "daq_st1", "family": "daq"}, {"id": "dc_main_st1", "family": "psu"}]


async def test_instance_templating_expands(tmp_path):
    module, _, db = await _build(tmp_path, instances=INSTANCES)
    try:
        ids = {c["id"] for c in module.list_checks()}
        assert "hardware.self_test:daq_st1" in ids
        assert "hardware.self_test:dc_main_st1" in ids
        # requires rewritten to the same instance
        st = next(c for c in module.list_checks() if c["id"] == "hardware.self_test:daq_st1")
        assert st["requires"] == ["hardware.instance_connected:daq_st1"]
        assert st["base_id"] == "hardware.self_test" and st["instance_id"] == "daq_st1"
    finally:
        await db.close()


async def test_disruptive_blocked_outside_maintenance(tmp_path):
    bridge = FakeBridge(online=True, replies={
        "hello.echo": lambda a: {"ok": True, "ts": time.time()},
        "health.check.hardware.instance_connected": lambda a: {"ok": True, "status": "pass"},
    })
    module, _, db = await _build(tmp_path, bridge, instances=INSTANCES)
    try:
        hid = await module.run(check_ids=["hardware.self_test:daq_st1"])  # disruptive
        by = {v["check_id"]: v for v in (await module.get_run(hid))["verdicts"]}
        assert by["hardware.self_test:daq_st1"]["status"] == "skipped"
        assert "maintenance" in by["hardware.self_test:daq_st1"]["summary"]
    finally:
        await db.close()


async def test_hardware_runs_in_maintenance(tmp_path):
    calls = []
    def rec(op):
        def fn(args):
            calls.append((op, args.get("instance_id")))
            return {"ok": True, "status": "pass", "summary": op, "data": {}}
        return fn
    bridge = FakeBridge(online=True, replies={
        "health.check.hardware.instance_connected": rec("ic"),
        "health.check.hardware.self_test": rec("st"),
    })
    module, _, db = await _build(tmp_path, bridge, instances=INSTANCES)
    module._maintenance = True  # station entered maintenance (LabVIEW-owned)
    try:
        hid = await module.run(check_ids=["hardware.instance_connected:daq_st1", "hardware.self_test:daq_st1"])
        by = {v["check_id"]: v for v in (await module.get_run(hid))["verdicts"]}
        assert by["hardware.instance_connected:daq_st1"]["status"] == "pass"
        assert by["hardware.self_test:daq_st1"]["status"] == "pass"
        # dispatched to base topic with the instance_id param
        assert ("st", "daq_st1") in calls
    finally:
        await db.close()


async def test_maintenance_state_from_retained(tmp_path):
    module, _, db = await _build(tmp_path, instances=INSTANCES)
    try:
        assert module._maintenance is False
        module._on_maintenance("tmf/st1/state/maintenance", {"state": "on"})
        assert module._maintenance is True
        module._on_maintenance("tmf/st1/state/maintenance", {"state": "off"})
        assert module._maintenance is False
    finally:
        await db.close()


# --- R4: known-issues catalog + signature matching + suggestions -----------


async def test_known_issues_loaded_and_searchable(tmp_path):
    module, _, db = await _build(tmp_path)
    try:
        assert module.get_known_issue("bridge.offline") is not None
        hits = module.list_known_issues(q="bridge")
        assert any(i["issue_id"] == "bridge.offline" for i in hits)
    finally:
        await db.close()


async def test_failure_matches_known_issue(tmp_path):
    bridge = FakeBridge(online=False)  # connected flag True -> bridge.online = fail
    module, _, db = await _build(tmp_path, bridge)
    try:
        hid = await module.run(check_ids=["bridge.online"])
        run = await module.get_run(hid)
        assert run["suggestions"] and run["suggestions"][0]["issue_id"] == "bridge.offline"
        assert run["suggestions"][0]["matched"] is True
        assert "remedy" in run["suggestions"][0]
        # persisted as a record + queryable
        sugs = await module.list_suggestions(matched=True)
        assert any(s["issue_id"] == "bridge.offline" for s in sugs)
    finally:
        await db.close()


async def test_unknown_signature_recorded(tmp_path):
    # huge min -> web.disk_space fails; no catalog entry for it -> matched False
    module, _, db = await _build(tmp_path, disk_min_gb=1e12)
    try:
        hid = await module.run(check_ids=["web.disk_space"])
        run = await module.get_run(hid)
        assert run["suggestions"][0]["matched"] is False
        assert run["suggestions"][0]["issue_id"] is None
        unknown = await module.list_suggestions(matched=False)
        assert unknown and unknown[0]["operator_ack"] is None
    finally:
        await db.close()


async def test_suggestion_ack(tmp_path):
    module, _, db = await _build(tmp_path, disk_min_gb=1e12)
    try:
        hid = await module.run(check_ids=["web.disk_space"])
        sid = (await module.get_run(hid))["suggestions"][0]["id"]
        assert await module.ack_suggestion(sid, "helped") is True
        rec = await module.list_suggestions()
        assert next(s for s in rec if s["id"] == sid)["operator_ack"] == "helped"
        assert await module.ack_suggestion("nope", "helped") is False
    finally:
        await db.close()

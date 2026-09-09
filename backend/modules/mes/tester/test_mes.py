"""mes standalone tester (CORE.md §6.2) — core + mes + folder transport + :memory: db."""

import json

import pytest

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from core.services.interlock import InterlockPort
from modules.mes.variants.default import DefaultMes


async def _build(tmp_path, *, gate=True, publish=True):
    db = Database(":memory:", station="st2", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, interlock=InterlockPort(),
        diag=Diagnostics("st2", "0.0.0", sinks=[lambda e: None]), station="st2",
    )
    config = {
        "stage": "st2", "provider": "folder",
        "gate": {"enabled": gate, "on_missing": "block"},
        "publish": {"enabled": publish},
        "folder": {
            "upstream_dir": str(tmp_path / "up"),
            "downstream_dir": str(tmp_path / "down"),
        },
    }
    module = DefaultMes.construct(core, config)
    await module.init()
    return module, core, db


@pytest.fixture
async def ctx(tmp_path):
    module, core, db = await _build(tmp_path)
    yield module, core, db, tmp_path
    await db.close()


def test_folder_dirs_resolve_outside_the_swappable_tree(tmp_path, monkeypatch):
    """cwd=run.dist on a frozen station: a relative upstream/downstream dir must resolve
    under TMF_STATE_DIR so an update swap can't rename the MES handoff files into the backup."""
    from modules.mes.providers.folder import FolderProvider
    monkeypatch.setenv("TMF_STATE_DIR", str(tmp_path / "deploy"))
    run_dist = tmp_path / "run.dist"
    run_dist.mkdir()
    monkeypatch.chdir(run_dist)
    p = FolderProvider({"upstream_dir": "data/mes/upstream", "downstream_dir": "data/mes/downstream"})
    assert p.upstream == tmp_path / "deploy" / "data" / "mes" / "upstream"
    assert p.downstream == tmp_path / "deploy" / "data" / "mes" / "downstream"


async def test_block_when_no_upstream(ctx):
    module, _, _, _ = ctx
    res = await module.check("SN1", {})
    assert res.allowed is False and "no PASS" in res.detail


async def test_allow_when_upstream_pass(ctx):
    module, _, _, tmp = ctx
    d = tmp / "up" / "PASS"; d.mkdir(parents=True)
    (d / "SN1.json").write_text("{}")
    res = await module.check("SN1", {})
    assert res.allowed is True and res.prior_result == "PASS"


async def test_block_when_upstream_fail(ctx):
    module, _, _, tmp = ctx
    d = tmp / "up" / "FAIL"; d.mkdir(parents=True)
    (d / "SN2.json").write_text("{}")
    res = await module.check("SN2", {})
    assert res.allowed is False and res.prior_result == "FAIL"


async def test_gate_disabled_allows(tmp_path):
    module, _, db = await _build(tmp_path, gate=False)
    try:
        assert (await module.check("SNX", {})).allowed is True
    finally:
        await db.close()


async def test_publish_writes_downstream(ctx):
    module, _, _, tmp = ctx
    await module.publish("SN3", "PASS", {"stage": "st2"})
    f = tmp / "down" / "PASS" / "SN3.json"
    assert f.exists()
    assert json.loads(f.read_text())["serial"] == "SN3"


async def test_run_finished_publishes_from_record(ctx):
    module, core, db, tmp = ctx
    await db.repo.put("run", {"serial_no": "SN9", "result": "FAIL", "model": "INV"},
                      id="R9", summary="run R9")
    await module._on_event("tmf/st2/event/run-finished",
                           {"type": "run-finished", "ts": 1.0, "payload": {"run_id": "R9", "result": "FAIL"}})
    assert (tmp / "down" / "FAIL" / "SN9.json").exists()


async def test_set_config_persists_and_toggles(ctx):
    module, core, db, _ = ctx
    await module.set_config(gate_enabled=False, publish_enabled=False)
    assert module.gate_enabled is False
    rec = await db.repo.get("mes_setting", "mes")
    assert rec["data"]["gate_enabled"] is False

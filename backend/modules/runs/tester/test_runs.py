"""runs standalone tester (CORE.md §6.2, §7). Core + runs + stub bridge + real db."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.runs.acquisition import AcquisitionError
from modules.runs.variants.default import DefaultRuns


class FakeBridge:
    online = True
    station = "st1"

    def __init__(self):
        self.requests = []

    async def request(self, op, args, timeout=None):
        self.requests.append((op, args))
        return {"id": "x", "ok": True, "result": {}}


@pytest.fixture
async def ctx():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    bridge = FakeBridge()
    core = CoreServices(
        db=db, bridge=bridge,
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]),
        station="st1",
    )
    module = DefaultRuns.construct(core, {})
    yield module, bridge, db
    await db.close()


def _event(etype, ts, **body):
    return {"type": etype, "ts": ts, "payload": body}


# --- run control -----------------------------------------------------------


async def test_run_start_resolves_id_and_mints_run_id(ctx):
    module, bridge, _ = ctx
    out = await module.run_start({"recipe_id": "demo"})
    op, args = bridge.requests[-1]
    assert op == "run.start"
    assert args["recipe_id"] == "demo" and args["run_id"]
    assert out["recipe_id"] == "demo" and out["run_id"] == args["run_id"]
    await module.run_abort()
    assert bridge.requests[-1] == ("run.abort", {})


async def test_run_start_from_barcode(ctx):
    # default acquisition is prefix length 3 -> "INV12345" resolves to "INV"
    module, bridge, _ = ctx
    out = await module.run_start({"barcode": "INV12345"})
    assert out["recipe_id"] == "INV"
    assert out["model"] == "INV" and out["serial_no"] == "INV12345"
    _, args = bridge.requests[-1]
    assert args["recipe_id"] == "INV"
    assert args["run_parameters"]["barcode"] == "INV12345"
    assert args["run_parameters"]["serial_no"] == "INV12345"
    # identity persisted on the run record
    run = await module.get_run(out["run_id"])
    assert run["data"]["model"] == "INV" and run["data"]["serial_no"] == "INV12345"


async def test_reset_data_purges_records(ctx):
    module, _, db = ctx
    await module._on_event("tmf/st1/event/run-started", _event("run-started", 1.0, run_id="R1"))
    await module._on_event("tmf/st1/event/run-finished", _event("run-finished", 1.2, run_id="R1", result="PASS"))
    await db.repo.put("error_log", {"level": "error", "message": "x"}, summary="e")
    await db.repo.put("action_log", {"user": "op", "action": "y"}, summary="a")
    assert await module.list_runs()  # has data
    out = await module.reset_data()
    assert out["deleted"]["run"] >= 1 and out["deleted"]["run_event"] >= 1
    assert out["deleted"]["error_log"] >= 1 and out["deleted"]["action_log"] >= 1
    assert await module.list_runs() == []
    assert await db.repo.query("run_event") == []
    assert await db.repo.query("error_log") == [] and await db.repo.query("action_log") == []


async def test_reset_data_targets_select(ctx):
    module, _, db = ctx
    await module._on_event("tmf/st1/event/run-finished", _event("run-finished", 1.0, run_id="R1", result="PASS"))
    await db.repo.put("error_log", {"level": "error", "message": "x"}, summary="e")
    # only the 'logs' target -> runs/reports untouched
    out = await module.reset_data(["logs"])
    assert "error_log" in out["deleted"] and "run" not in out["deleted"]
    assert await module.list_runs()                       # run record survived
    # recipes/users delegate via get_contract; absent here -> 0, no crash
    out2 = await module.reset_data(["recipes", "users"])
    assert out2["deleted"]["recipes"] == 0 and out2["deleted"]["users"] == 0


async def test_profile_shape(ctx):
    module, _, _ = ctx
    p = module.profile()
    assert p["acquisition"]["default_mode"] == "barcode"
    assert "identity" in p and "live_variables" in p and "analytics" in p and "ui" in p
    assert p["ui"]["verdict_banner"] is True


async def test_run_start_requires_recipe_or_barcode(ctx):
    module, _, _ = ctx
    with pytest.raises(AcquisitionError):
        await module.run_start({})


async def test_acquisition_config(ctx):
    module, _, _ = ctx
    cfg = module.acquisition_config()
    assert cfg["default_mode"] == "barcode"
    assert cfg["barcode"]["length"] == 3


# --- event -> records ------------------------------------------------------


async def test_run_lifecycle_persists_records(ctx):
    module, _, db = ctx
    await module._on_event("tmf/st1/event/run-started", _event("run-started", 1.0, run_id="R1", recipe="demo"))
    await module._on_event("tmf/st1/event/step-completed", _event("step-completed", 1.1, run_id="R1", step_id="s1", status="PASSED"))
    await module._on_event("tmf/st1/event/run-finished", _event("run-finished", 1.2, run_id="R1", result="PASS"))

    run = await module.get_run("R1")
    assert run["data"]["status"] == "finished"
    assert run["data"]["result"] == "PASS"
    assert run["data"]["started_ts"] == 1.0
    assert run["data"]["finished_ts"] == 1.2

    events = await db.repo.query("run_event")
    assert [e["data"]["type"] for e in events] == ["run-started", "step-completed", "run-finished"]


async def test_test_result_rows_accumulate_on_run(ctx):
    module, _, db = ctx
    await module._on_event("tmf/st1/event/run-started", _event("run-started", 1.0, run_id="R1", recipe_id="INV"))
    await module._on_event("tmf/st1/event/test-result",
                           _event("test-result", 1.1, run_id="R1", serial_no=1, test_name="OVP", expected="320", measured="319.4", result="PASS", cycle_time_ms=412))
    await module._on_event("tmf/st1/event/test-result",
                           _event("test-result", 1.2, run_id="R1", serial_no=2, test_name="UVP", result="FAIL"))

    run = await module.get_run("R1")
    rows = run["data"]["results"]
    assert len(rows) == 2
    assert rows[0]["test_name"] == "OVP" and rows[0]["result"] == "PASS"
    assert rows[1]["result"] == "FAIL"
    assert run["data"]["recipe_id"] == "INV"  # preserved across events (merge)
    # rows are also in append-only history
    types = [e["data"]["type"] for e in await db.repo.query("run_event")]
    assert types.count("test-result") == 2


async def test_run_aborted_sets_status(ctx):
    module, _, _ = ctx
    await module._on_event("tmf/st1/event/run-started", _event("run-started", 1.0, run_id="R2"))
    await module._on_event("tmf/st1/event/run-aborted", _event("run-aborted", 1.5, run_id="R2", reason="estop"))
    run = await module.get_run("R2")
    assert run["data"]["status"] == "finished" and run["data"]["result"] == "ABORTED"


async def test_non_run_events_ignored(ctx):
    module, _, db = ctx
    await module._on_event("tmf/st1/event/heartbeat", _event("heartbeat", 1.0))
    assert await db.repo.query("run_event") == []
    assert await module.list_runs() == []


async def test_event_without_run_id_still_appended(ctx):
    module, _, db = ctx
    await module._on_event("tmf/st1/event/safety-trip", _event("safety-trip", 2.0, reason="overvoltage"))
    events = await db.repo.query("run_event")
    assert len(events) == 1 and events[0]["data"]["type"] == "safety-trip"
    assert await module.list_runs() == []  # no run record without a run_id


# --- REST ------------------------------------------------------------------


def _client(module):
    app = FastAPI()
    app.include_router(module.router)
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_rest_surface(ctx):
    module, bridge, _ = ctx
    await module._on_event("tmf/st1/event/run-started", _event("run-started", 1.0, run_id="R1"))
    async with _client(module) as c:
        started = await c.post("/runs/start", json={"recipe_id": "demo"})
        assert started.status_code == 200
        data = started.json()
        assert data["recipe_id"] == "demo" and data["run_id"]
        op, args = bridge.requests[-1]
        assert op == "run.start" and args["recipe_id"] == "demo"

        # no recipe_id and no barcode -> 422
        bad = await c.post("/runs/start", json={})
        assert bad.status_code == 422

        acq = await c.get("/runs/acquisition")
        assert acq.status_code == 200 and acq.json()["default_mode"] == "barcode"

        ids = [r["id"] for r in (await c.get("/runs")).json()]
        assert "R1" in ids

        one = await c.get("/runs/R1")
        assert one.status_code == 200 and one.json()["data"]["status"] == "running"

        missing = await c.get("/runs/none")
        assert missing.status_code == 404


# --- WS fan-out ------------------------------------------------------------


class FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        pass


async def test_station_ws_fans_out_events(ctx):
    module, _, _ = ctx
    ws = FakeWS()
    task = asyncio.create_task(module.station_ws(ws))
    await asyncio.sleep(0.02)
    await module._on_event("tmf/st1/event/run-started", _event("run-started", 1.0, run_id="R1"))
    await asyncio.sleep(0.02)
    task.cancel()
    assert any(e["type"] == "run-started" for e in ws.sent)


async def test_diag_ws_fans_out_diag(ctx):
    module, _, _ = ctx
    ws = FakeWS()
    task = asyncio.create_task(module.diag_ws(ws))
    await asyncio.sleep(0.02)
    module._on_diag("tmf/st1/diag", {"level": "warning", "message": "hi"})
    await asyncio.sleep(0.02)
    task.cancel()
    assert ws.sent[-1] == {"level": "warning", "message": "hi"}

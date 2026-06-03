"""runs standalone tester (CORE.md §6.2, §7). Core + runs + stub bridge + real db."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
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


async def test_run_start_and_abort_send_commands(ctx):
    module, bridge, _ = ctx
    await module.run_start({"recipe": "demo"})
    assert bridge.requests[-1] == ("run.start", {"recipe": "demo"})
    await module.run_abort()
    assert bridge.requests[-1] == ("run.abort", {})


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
        started = await c.post("/runs/start", json={"recipe": "demo"})
        assert started.status_code == 200
        assert bridge.requests[-1] == ("run.start", {"recipe": "demo"})

        runs = await c.get("/runs")
        assert runs.status_code == 200
        assert [r["id"] for r in runs.json()] == ["R1"]

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

"""daq standalone tester (CORE.md §6.2) — streaming. Core + daq + stub bridge."""

import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI, WebSocketDisconnect
from httpx import ASGITransport
from starlette.testclient import TestClient

from core.framework.contract import CoreServices
from core.services.diagnostics import Diagnostics
from modules.daq.variants.default import DefaultDaq


class FakeBridge:
    online = True
    station = "st1"

    def __init__(self):
        self.requests = []
        self._latest = {}
        self.replies = {}  # op -> reply dict
        # An unpicklable member: mirrors the real bridge/db graph (sqlite3 conn).
        # Guards the regression where a route leaked a bound-method default and
        # FastAPI deep-copied module->core->bridge per request (TypeError -> 500).
        self._unpicklable = threading.Lock()

    async def request(self, op, args, *, station=None, timeout=None):
        self.requests.append((op, args))
        return self.replies.get(op, {"id": "x", "ok": True, "result": {}})

    def latest(self, sub_topic):
        return self._latest.get(sub_topic)


def _module():
    bridge = FakeBridge()
    core = CoreServices(
        bridge=bridge,
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]),
        station="st1",
    )
    return DefaultDaq.construct(core, {}), bridge


def _handler(module, signal):
    return next(h for t, h in module.mqtt_handlers if t == f"stream/{signal}")


# --- contract logic --------------------------------------------------------


async def test_stream_start_stop_sends_commands_and_tracks_running():
    module, bridge = _module()
    assert module.is_running("ai") is False

    await module.ai_stream_start({"rate": 1000})
    assert bridge.requests[-1] == ("daq.ai.stream.start", {"rate": 1000})
    assert module.is_running("ai") is True

    await module.ai_stream_stop()
    assert bridge.requests[-1] == ("daq.ai.stream.stop", {})
    assert module.is_running("ai") is False


async def test_latest_proxies_bridge_cache():
    module, bridge = _module()
    bridge._latest["stream/ai"] = {"seq": 7, "values": {"ai0": 5.0}}
    assert module.latest("ai") == {"seq": 7, "values": {"ai0": 5.0}}
    assert module.latest("di") is None


# --- WS handler logic (in-loop, no transport) ------------------------------


class FakeWS:
    def __init__(self, station=None):
        self.accepted = False
        self.sent = []
        self.closed = None
        self.query_params = {} if station is None else {"station": station}

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


async def test_ws_gates_when_not_running():
    module, _ = _module()
    ws = FakeWS()
    await module.stream_ws(ws, "ai")
    assert ws.accepted is True
    assert ws.closed == (4409, "stream not running")


async def test_ws_snapshot_then_live_frames():
    module, bridge = _module()
    module._running["ai"] = True
    bridge._latest["stream/ai"] = {"snap": True}
    ws = FakeWS()
    task = asyncio.create_task(module.stream_ws(ws, "ai"))
    await asyncio.sleep(0.05)            # accept + snapshot + subscribe
    _handler(module, "ai")("tmf/st1/stream/ai", {"seq": 2})
    await asyncio.sleep(0.05)            # drain + send
    task.cancel()
    assert ws.sent[0] == {"snap": True}                  # snapshot-on-join
    assert {"seq": 2, "station": "st1"} in ws.sent       # live frame, station-tagged


async def test_values_ws_snapshot_then_live():
    module, _ = _module()
    # a value seen before the client joins -> snapshot
    module._on_value("tmf/st1/value/vbus_main", {"value": 264.0, "ts": 1.0})
    assert module._values[("st1", "vbus_main")] == {"name": "vbus_main", "station": "st1", "value": 264.0, "ts": 1.0}
    ws = FakeWS()
    task = asyncio.create_task(module.stream_values_ws(ws))
    await asyncio.sleep(0.05)            # accept + snapshot + subscribe
    module._on_value("tmf/st1/value/temp_c", {"value": 41.2, "ts": 2.0})
    await asyncio.sleep(0.05)            # drain + send
    task.cancel()
    assert {"name": "vbus_main", "station": "st1", "value": 264.0, "ts": 1.0} in ws.sent  # snapshot
    assert {"name": "temp_c", "station": "st1", "value": 41.2, "ts": 2.0} in ws.sent      # live


# --- WS over the real ASGI transport (routing + gating) --------------------


def _app():
    module, bridge = _module()
    app = FastAPI()
    app.include_router(module.router)
    return app, module, bridge


def test_ws_route_gating_real_transport():
    app, module, _ = _app()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/instruments/daq/ai/stream/ws") as ws:
            ws.receive_json()
    assert ei.value.code == 4409


def test_ws_route_snapshot_real_transport():
    app, module, bridge = _app()
    module._running["ai"] = True
    bridge._latest["stream/ai"] = {"snap": 1}
    client = TestClient(app)
    with client.websocket_connect("/instruments/daq/ai/stream/ws") as ws:
        assert ws.receive_json() == {"snap": 1}


# --- variables -------------------------------------------------------------


async def test_variable_read_prefers_retained_cache():
    module, bridge = _module()
    bridge._latest["value/vbus_main"] = {"value": 264.0, "ts": 1.0}
    assert await module.variable_read("vbus_main") == {"value": 264.0, "ts": 1.0}
    assert bridge.requests == []  # no command needed


async def test_variable_read_falls_back_to_command():
    module, bridge = _module()
    bridge.replies["variable.read"] = {"ok": True, "result": {"value": 5.0, "ts": 2.0}}
    assert await module.variable_read("missing") == {"value": 5.0, "ts": 2.0}
    assert bridge.requests[-1] == ("variable.read", {"name": "missing"})


async def test_variable_read_failure_raises():
    module, bridge = _module()
    bridge.replies["variable.read"] = {"ok": False, "error": {"message": "no such variable"}}
    with pytest.raises(ValueError, match="no such variable"):
        await module.variable_read("nope")


async def test_variable_write_sends_command():
    module, bridge = _module()
    reply = await module.variable_write("setpoint", 12.5)
    assert bridge.requests[-1] == ("variable.write", {"name": "setpoint", "value": 12.5})
    assert reply["ok"] is True


def _client(app):
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_stream_rest_start_stop():
    # Regression: the start/stop routes must not leak a bound-method param
    # default. FastAPI deep-copies handler defaults per request; with the bridge
    # carrying an unpicklable member (FakeBridge._unpicklable) the old code would
    # crash with TypeError -> 500 here.
    app, module, bridge = _app()
    async with _client(app) as c:
        r = await c.post("/instruments/daq/ai/stream/start", json={"rate": 1000})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert bridge.requests[-1] == ("daq.ai.stream.start", {"rate": 1000})
        assert module.is_running("ai") is True

        s = await c.post("/instruments/daq/ai/stream/stop")
        assert s.status_code == 200
        assert bridge.requests[-1] == ("daq.ai.stream.stop", {})
        assert module.is_running("ai") is False


async def test_variable_rest_read_and_write():
    app, module, bridge = _app()
    bridge._latest["value/vbus_main"] = {"value": 264.0, "ts": 1.0}
    async with _client(app) as c:
        r = await c.get("/variables/vbus_main/value")
        assert r.status_code == 200 and r.json() == {"value": 264.0, "ts": 1.0}

        w = await c.put("/variables/setpoint/value", json={"value": 9})
        assert w.status_code == 200
        assert bridge.requests[-1] == ("variable.write", {"name": "setpoint", "value": 9})


async def test_variable_rest_errors():
    app, module, bridge = _app()
    bridge.replies["variable.read"] = {"ok": False, "error": {"message": "unknown"}}
    async with _client(app) as c:
        bad = await c.get("/variables/ghost/value")
        assert bad.status_code == 502
        missing = await c.put("/variables/x/value", json={"nope": 1})
        assert missing.status_code == 422

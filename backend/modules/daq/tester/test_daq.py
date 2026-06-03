"""daq standalone tester (CORE.md §6.2) — streaming. Core + daq + stub bridge."""

import asyncio

import pytest
from fastapi import FastAPI, WebSocketDisconnect
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

    async def request(self, op, args, timeout=None):
        self.requests.append((op, args))
        return {"id": "x", "ok": True, "result": {}}

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
    def __init__(self):
        self.accepted = False
        self.sent = []
        self.closed = None

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
    assert ws.sent[0] == {"snap": True}  # snapshot-on-join
    assert {"seq": 2} in ws.sent         # live frame


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

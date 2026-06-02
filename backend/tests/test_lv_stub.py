"""The reference LabVIEW stub (LABVIEW_BRIDGE.md §12), driven over a real broker.

Proves the stub satisfies CORE.md §10 #5 (hello.echo), #6 (stream + retained
value + diag flow LV->Py), and the online/offline status transition (#7 via a
graceful offline announce; the LWT-on-crash path is the same retained topic).
Skipped without mosquitto.
"""

import asyncio

import pytest

from core.services.bridge import BridgeClient
from tests._mqtt import Broker, find_mosquitto
from tools.lv_stub import LabviewStub

pytestmark = pytest.mark.skipif(find_mosquitto() is None, reason="mosquitto not installed")


@pytest.fixture
async def broker(tmp_path):
    b = Broker(tmp_path)
    b.start()
    yield b
    b.stop()


async def _until(cond, what, timeout=6.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out: {what}")


async def test_stub_full_surface(broker):
    stub = LabviewStub(broker.host, broker.port, station="st1",
                       stream_hz=20.0, value_period=0.2, status_period=0.5)
    await stub.start()
    bridge = BridgeClient("st1", host=broker.host, port=broker.port)
    frames: dict = {"stream": [], "value": [], "diag": []}
    try:
        await bridge.connect(wait_timeout=5)
        await _until(lambda: bridge.online, "bridge online")

        bridge.subscribe("stream/ai", lambda t, p: frames["stream"].append(p))
        bridge.subscribe("value/vbus_main", lambda t, p: frames["value"].append(p))
        bridge.subscribe("diag", lambda t, p: frames["diag"].append(p))
        await asyncio.sleep(0.3)  # let subscriptions land

        # #5: hello.echo round-trip
        reply = await bridge.request("hello.echo", {"msg": "hi"}, timeout=5)
        assert reply["ok"] is True
        assert reply["result"]["echoed"] == {"msg": "hi"}

        # #6: stream frame + retained value + diag event all flow LV->Py
        await _until(lambda: frames["stream"], "stream frame")
        await _until(lambda: frames["value"], "value")
        await _until(lambda: frames["diag"], "diag")
        assert "ai0" in frames["stream"][0]["values"]
        assert frames["stream"][0]["seq"] >= 1
        assert isinstance(frames["value"][0]["value"], (int, float))
        assert frames["diag"][0]["subsystem"] == "stub"

        # status online in the retained topic
        assert bridge.online is True
    finally:
        await bridge.disconnect()
        await stub.stop()


async def test_stub_offline_on_stop(broker):
    stub = LabviewStub(broker.host, broker.port, station="st1", status_period=10.0)
    await stub.start()
    bridge = BridgeClient("st1", host=broker.host, port=broker.port)
    try:
        await bridge.connect(wait_timeout=5)
        await _until(lambda: bridge.online, "bridge online")
        await stub.stop()
        await _until(lambda: not bridge.online, "bridge offline after stub stop")
        assert bridge.online is False
    finally:
        await bridge.disconnect()

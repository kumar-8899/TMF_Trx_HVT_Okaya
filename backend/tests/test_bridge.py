"""Bridge client (CORE.md §1, §9; LABVIEW_BRIDGE §5-§7).

Unit tests run anywhere. The round-trip tests need a real broker and are skipped
when mosquitto is not installed (CI installs it).
"""

import asyncio

import pytest

from core.services.bridge import BridgeClient, BridgeError, BridgeTimeout, topic_matches
from tests._mqtt import Broker, FakeLabview, find_mosquitto

# --- unit (no broker) -----------------------------------------------------


@pytest.mark.parametrize(
    "filter_,topic,expected",
    [
        ("tmf/st1/status", "tmf/st1/status", True),
        ("tmf/st1/cmd/+", "tmf/st1/cmd/hello.echo", True),
        ("tmf/st1/cmd/+", "tmf/st1/cmd/resp/abc", False),
        ("tmf/+/event/#", "tmf/st1/event/run-started", True),
        ("tmf/+/event/#", "tmf/st1/value/vbus_main", False),
        ("tmf/st1/#", "tmf/st1/stream/ai", True),
        ("tmf/st1/value/vbus_main", "tmf/st1/value/other", False),
    ],
)
def test_topic_matches(filter_, topic, expected):
    assert topic_matches(filter_, topic) is expected


async def test_publish_request_require_connection():
    bridge = BridgeClient("st1")
    assert bridge.online is False
    with pytest.raises(BridgeError):
        await bridge.publish("value/x", {"value": 1})
    with pytest.raises(BridgeError):
        await bridge.request("hello.echo", {})


class _FakeTopic:
    def __init__(self, value):
        self.value = value


class _FakeMsg:
    def __init__(self, topic, payload):
        self.topic = _FakeTopic(topic)
        self.payload = payload
        self.properties = None


def test_latest_frame_cache():
    # _dispatch caches the latest payload per topic (BRIDGE §6) for snapshot-on-join.
    bridge = BridgeClient("st1")
    assert bridge.latest("stream/ai") is None
    bridge._dispatch(_FakeMsg("tmf/st1/stream/ai", b'{"seq": 1, "values": {"ai0": 5.0}}'))
    bridge._dispatch(_FakeMsg("tmf/st1/stream/ai", b'{"seq": 2, "values": {"ai0": 6.0}}'))
    bridge._dispatch(_FakeMsg("tmf/st1/value/vbus_main", b'{"value": 264.0}'))
    assert bridge.latest("stream/ai") == {"seq": 2, "values": {"ai0": 6.0}}
    assert bridge.latest("value/vbus_main") == {"value": 264.0}


# --- integration (real broker) --------------------------------------------

pytestmark_broker = pytest.mark.skipif(
    find_mosquitto() is None, reason="mosquitto not installed"
)


@pytest.fixture
async def broker(tmp_path):
    b = Broker(tmp_path)
    b.start()
    yield b
    b.stop()


@pytestmark_broker
async def test_link_goes_online_from_retained_status(broker):
    lv = FakeLabview(broker.host, broker.port)
    await lv.start()
    bridge = BridgeClient("st1", host=broker.host, port=broker.port)
    try:
        assert await bridge.connect(wait_timeout=5) is True
        await _until(lambda: bridge.online, "bridge online")
        assert bridge.online is True
    finally:
        await bridge.disconnect()
        await lv.stop()


@pytestmark_broker
async def test_request_round_trip(broker):
    lv = FakeLabview(broker.host, broker.port)
    await lv.start()
    bridge = BridgeClient("st1", host=broker.host, port=broker.port)
    try:
        await bridge.connect(wait_timeout=5)
        await _until(lambda: bridge.online, "bridge online")
        reply = await bridge.request("hello.echo", {"msg": "hi"}, timeout=5)
        assert reply["ok"] is True
        assert reply["result"]["echoed"] == {"msg": "hi"}
        assert reply["result"]["station"] == "st1"
    finally:
        await bridge.disconnect()
        await lv.stop()


@pytestmark_broker
async def test_subscribe_receives_stream_frame(broker):
    lv = FakeLabview(broker.host, broker.port)
    await lv.start()
    bridge = BridgeClient("st1", host=broker.host, port=broker.port)
    got: list = []
    try:
        await bridge.connect(wait_timeout=5)
        await _until(lambda: bridge.online, "bridge online")
        bridge.subscribe("stream/ai", lambda topic, payload: got.append((topic, payload)))
        await asyncio.sleep(0.3)  # let the subscribe land
        await lv.publish("stream/ai", {"t": 1.0, "seq": 1, "values": {"ai0": 5.0}}, qos=0)
        await _until(lambda: got, "stream frame received")
        topic, payload = got[0]
        assert topic == "tmf/st1/stream/ai"
        assert payload["values"]["ai0"] == 5.0
    finally:
        await bridge.disconnect()
        await lv.stop()


@pytestmark_broker
async def test_link_goes_offline_when_status_flips(broker):
    lv = FakeLabview(broker.host, broker.port)
    await lv.start()
    bridge = BridgeClient("st1", host=broker.host, port=broker.port)
    try:
        await bridge.connect(wait_timeout=5)
        await _until(lambda: bridge.online, "bridge online")
        await lv.set_status("offline")
        await _until(lambda: not bridge.online, "bridge offline")
        assert bridge.online is False
    finally:
        await bridge.disconnect()
        await lv.stop()


@pytestmark_broker
async def test_request_timeout_when_no_responder(broker):
    bridge = BridgeClient("st1", host=broker.host, port=broker.port)
    try:
        await bridge.connect(wait_timeout=5)
        with pytest.raises(BridgeTimeout):
            await bridge.request("nobody.home", {}, timeout=0.5)
    finally:
        await bridge.disconnect()


async def _until(cond, what: str, timeout: float = 5.0) -> None:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for: {what}")

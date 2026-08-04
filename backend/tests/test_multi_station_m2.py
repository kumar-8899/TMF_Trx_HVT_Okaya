"""M2 — MultiStationBridge: N connections, required `station` kwarg, per-station link
state (MULTI_STATION.md §2, §9 slice M2)."""

import json
import socket
import uuid

import paho.mqtt.client as _paho
import pytest

from core.services.bridge import BridgeError, MultiStationBridge

HOST, PORT = "127.0.0.1", 1883


# ---- contract (no broker) -------------------------------------------------

def test_stations_and_offline_link_map():
    b = MultiStationBridge(["st1", "st2"], host=HOST, port=PORT)
    assert b.stations == ["st1", "st2"]
    assert b.link_map() == {"st1": "offline", "st2": "offline"}   # not connected
    assert b.any_link_online is False and b.online is False


def test_empty_stations_rejected():
    with pytest.raises(BridgeError):
        MultiStationBridge([])


def test_unknown_station_rejected():
    b = MultiStationBridge(["st1"], host=HOST, port=PORT)
    with pytest.raises(BridgeError):
        b.link_status("st2")


def test_station_is_required_keyword():
    b = MultiStationBridge(["st1"], host=HOST, port=PORT)
    with pytest.raises(TypeError):
        b.request("hello.echo", {})        # missing station -> TypeError, never a default
    with pytest.raises(TypeError):
        b.publish("value/x", {"v": 1})     # missing station


# ---- live per-station routing ---------------------------------------------

def _broker_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


class _Responder:
    """paho client answering cmd/+ for several stations, tagging the station it saw."""

    def __init__(self, stations):
        self.stations = stations
        self._c = _paho.Client(_paho.CallbackAPIVersion.VERSION2,
                               client_id=f"resp-{uuid.uuid4().hex[:6]}", protocol=_paho.MQTTv311)
        self._c.on_connect = self._on_connect
        self._c.on_message = self._on_message
        self._c.connect(HOST, PORT, 30)
        self._c.loop_start()

    def _on_connect(self, c, u, f, rc, props=None):
        for st in self.stations:
            c.publish(f"tmf/{st}/status", json.dumps({"state": "online"}), qos=1, retain=True)
            c.subscribe(f"tmf/{st}/cmd/+", qos=1)

    def _on_message(self, c, u, m):
        st = m.topic.split("/")[1]
        req = json.loads(m.payload)
        if req.get("reply_to"):
            c.publish(req["reply_to"],
                      json.dumps({"id": req.get("id"), "ok": True, "station_seen": st}), qos=1)

    def close(self):
        for st in self.stations:
            self._c.publish(f"tmf/{st}/status", json.dumps({"state": "offline"}), qos=1, retain=True)
        self._c.loop_stop()
        self._c.disconnect()


@pytest.mark.skipif(not _broker_up(), reason="no MQTT broker on 127.0.0.1:1883")
async def test_request_routes_to_the_addressed_station():
    a, b = f"m2a_{uuid.uuid4().hex[:4]}", f"m2b_{uuid.uuid4().hex[:4]}"
    responder = _Responder([a, b])
    bridge = MultiStationBridge([a, b], host=HOST, port=PORT)
    try:
        assert await bridge.connect(5.0) is True
        r_a = await bridge.request("hello.echo", {}, station=a, timeout=5.0)
        r_b = await bridge.request("hello.echo", {}, station=b, timeout=5.0)
        assert r_a["station_seen"] == a         # each request hit its own socket
        assert r_b["station_seen"] == b
    finally:
        await bridge.disconnect()
        responder.close()

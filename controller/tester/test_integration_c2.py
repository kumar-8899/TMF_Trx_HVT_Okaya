"""C2 live acceptance (PYTHON_CONTROLLER.md §16 C2) against a real broker.

Skipped when no broker. Proves controller-owned instruments are reachable by name:
variable.read/write round-trip with scale/clamp, the retained value/<name> snapshot is
warmed, and instrument.test opens the instance and reports its identity — no execution."""

import json
import socket
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

from controller.bridge.client import StationClient
from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import StationVariables
from controller.loop import AsyncLoopThread
from controller.serve import register_core_ops, register_station_ops
from tester import _fakelib

HOST, PORT = "127.0.0.1", 1883


def _broker_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _broker_up(), reason="no MQTT broker on 127.0.0.1:1883")

_MAP = {"signals": {
    "supply_voltage": {"instance": "psu1", "read": "measure_voltage", "write": "set_voltage",
                       "clamp": {"min": 0.0, "max": 30.0}, "units": "V"},
    "supply_current": {"instance": "psu1", "read": "measure_current", "units": "A"},
}, "actions": {}}


class _Probe:
    def __init__(self, station):
        self.station = station
        self.replies = {}
        self.retained = {}
        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"probe-{uuid.uuid4().hex[:6]}", protocol=mqtt.MQTTv311)
        self._c.on_message = self._on_message
        self._c.connect(HOST, PORT, 30)
        self._c.subscribe(f"tmf/{station}/#", qos=1)
        self._c.loop_start()

    def _on_message(self, c, u, m):
        try:
            p = json.loads(m.payload)
        except Exception:  # noqa: BLE001
            return
        if "/cmd/resp/" in m.topic:
            self.replies[p.get("id")] = p
        elif "/value/" in m.topic:
            self.retained[m.topic.split("/value/")[1]] = p

    def request(self, op, args, timeout=5.0):
        rid = uuid.uuid4().hex
        self._c.publish(f"tmf/{self.station}/cmd/{op}",
                        json.dumps({"id": rid, "op": op, "args": args,
                                    "reply_to": f"tmf/{self.station}/cmd/resp/probe"}), qos=1)
        end = time.time() + timeout
        while time.time() < end:
            if rid in self.replies:
                return self.replies[rid]
            time.sleep(0.02)
        raise AssertionError(f"no reply for {op}")

    def close(self):
        self._c.loop_stop()
        self._c.disconnect()


def test_c2_variables_and_instrument_test():
    lib = _fakelib.ensure_registered()
    station = f"c2_{uuid.uuid4().hex[:6]}"
    loop = AsyncLoopThread()
    loop.start()
    registry = InstrumentRegistry(loop)
    registry.build([{"id": "psu1", "library": lib, "simulated": True, "params": {"resource": "Z"}}])
    loop.run(registry.connect_all())

    probe = _Probe(station)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    register_station_ops(client, StationVariables(station, _MAP, registry, loop), registry, loop)
    try:
        client.start()
        assert client.wait_connected(5.0)

        # read: sim returns 5.0 V
        r = probe.request("variable.read", {"name": "supply_voltage"})
        assert r["ok"] is True and r["result"]["value"] == 5.0 and r["result"]["units"] == "V"

        # write clamps 100 -> 30 and warms the retained value/<name>
        w = probe.request("variable.write", {"name": "supply_voltage", "value": 100.0})
        assert w["ok"] is True and w["result"]["written"] == 30.0 and w["result"]["clamped"] is True
        end = time.time() + 3.0
        while time.time() < end and "supply_voltage" not in probe.retained:
            time.sleep(0.02)
        assert probe.retained["supply_voltage"]["value"] == 30.0

        # instrument.test opens + identifies
        t = probe.request("instrument.test", {"id": "psu1"})
        assert t["ok"] is True and t["status"] == "pass" and "FAKEPSU" in t["identity"]

        # unknown signal -> structured failure, not silence
        bad = probe.request("variable.read", {"name": "nope"})
        assert bad["ok"] is False
    finally:
        client.stop()
        loop.run(registry.disconnect_all())
        loop.stop()
        probe.close()

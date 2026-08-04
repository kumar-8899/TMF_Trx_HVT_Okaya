"""C7 live: a `safety.trip` over the broker cuts outputs on the reflex thread, publishes
event/safety-trip (no run_id) to the affected station, faults the station so run.start is
refused, and `safety.clear` recovers it. Skipped when no broker."""

import json
import socket
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

import controller.step_types  # noqa: F401
from controller.bridge.client import StationClient
from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import StationVariables
from controller.loop import AsyncLoopThread
from controller.runstate import RunEngine
from controller.safety import SafetyController, SafetyMap, parse_monitors
from controller.serve import register_core_ops, register_run_ops, register_safety_ops
from tester import _fakelib

HOST, PORT = "127.0.0.1", 1883


def _broker_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _broker_up(), reason="no MQTT broker on 127.0.0.1:1883")


class _Probe:
    def __init__(self, station):
        self.station = station
        self.trips = []
        self.replies = {}
        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"probe-{uuid.uuid4().hex[:6]}", protocol=mqtt.MQTTv311)
        self._c.on_message = self._on
        self._c.connect(HOST, PORT, 30)
        self._c.subscribe(f"tmf/{station}/#", qos=0)
        self._c.loop_start()

    def _on(self, c, u, m):
        try:
            p = json.loads(m.payload)
        except Exception:  # noqa: BLE001
            return
        if m.topic.endswith("/event/safety-trip"):
            self.trips.append(p)
        elif "/cmd/resp/probe" in m.topic:
            self.replies[p.get("id")] = p

    def cmd(self, op, args, timeout=5.0):
        rid = uuid.uuid4().hex
        self._c.publish(f"tmf/{self.station}/cmd/{op}",
                        json.dumps({"id": rid, "op": op, "args": args,
                                    "reply_to": f"tmf/{self.station}/cmd/resp/probe"}), qos=1)
        end = time.time() + timeout
        while time.time() < end and rid not in self.replies:
            time.sleep(0.02)
        return self.replies.get(rid, {})

    def close(self):
        self._c.loop_stop()
        self._c.disconnect()


def test_c7_trip_over_broker_faults_then_clears():
    station = f"c7_{uuid.uuid4().hex[:6]}"
    lib = _fakelib.ensure_registered()
    loop = AsyncLoopThread(); loop.start()
    reg = InstrumentRegistry(loop)
    reg.build([{"id": "psu", "library": lib, "simulated": True,
                "params": {"resource": station}, "stations": [station]}])
    loop.run(reg.connect_all())

    probe = _Probe(station)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    variables = StationVariables(station, {"signals": {}}, reg, loop)
    engine = RunEngine(station, variables=variables, emit=lambda t, p: None,
                       recipe_fetch=lambda rid, ver: {"steps": []},
                       safe_state=lambda: loop.run(reg.safe_state_station(station)),
                       diag=lambda *a, **k: None)
    register_run_ops(client, engine)

    smap = SafetyMap(parse_monitors([{"id": "estop", "scope": "pc"}]),
                     [station], {"psu": [station]})
    safety = SafetyController(smap, reg, loop, {station: engine},
                             (lambda st, sub, p: client.publish(sub, p)))
    register_safety_ops(client, safety)
    safety.start()
    try:
        client.start()
        assert client.wait_connected(5.0)

        r = probe.cmd("safety.trip", {"monitor_id": "estop"})
        assert r["ok"] is True and r["accepted"] is True

        deadline = time.time() + 3
        while time.time() < deadline and not probe.trips:
            time.sleep(0.02)
        assert probe.trips and probe.trips[0]["payload"]["monitor_id"] == "estop"
        assert "run_id" not in probe.trips[0]                  # a station fact, no run_id
        assert reg.is_faulted("psu")

        start = probe.cmd("run.start", {"recipe_id": "x", "run_id": "r1"})
        assert start["accepted"] is False and start["error"] == "station_faulted"

        clr = probe.cmd("safety.clear", {"monitor_id": "estop"})
        assert clr["ok"] is True and station in clr["cleared_stations"]
        assert not reg.is_faulted("psu")
        ok = probe.cmd("run.start", {"recipe_id": "x", "run_id": "r2"})
        assert ok["accepted"] is True                          # recovered, accepts runs again
    finally:
        safety.stop()
        client.stop()
        probe.close()
        loop.run(reg.disconnect_all())
        loop.stop()

"""C6 live: daq.ai.stream.start over the broker actually streams stream/ai frames to a
subscriber, and stop halts them. Skipped when no broker."""

import json
import socket
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

from controller.bridge.client import StationClient
from controller.daq import DaqController, register_daq_ops
from controller.serve import register_core_ops

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
        self.frames = []
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
        if m.topic.endswith("/stream/ai"):
            self.frames.append(p)
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


def test_c6_ai_stream_flows_then_stops():
    station = f"c6_{uuid.uuid4().hex[:6]}"
    probe = _Probe(station)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    daq = DaqController(station, (lambda sub, p, qos: client.publish(sub, p, qos=qos)),
                        config={"rate_hz": 100, "batch": 5, "ai_channels": ["ai0"], "simulated": True})
    register_daq_ops(client, daq)
    try:
        client.start()
        assert client.wait_connected(5.0)
        r = probe.cmd("daq.ai.stream.start", {})
        assert r["ok"] is True and r["started"] is True
        time.sleep(0.3)
        got = len(probe.frames)
        assert got >= 2 and probe.frames[0]["signal"] == "ai"
        assert len(probe.frames[0]["channels"]["ai0"]) == 5      # batched
        stop = probe.cmd("daq.ai.stream.stop", {})
        assert stop["stopped"] is True
        time.sleep(0.2)
        after = len(probe.frames)
        time.sleep(0.2)
        assert len(probe.frames) == after                        # halted
    finally:
        daq.stop_all()
        client.stop()
        probe.close()

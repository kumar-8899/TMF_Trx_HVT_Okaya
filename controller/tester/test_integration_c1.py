"""C1 live acceptance (PYTHON_CONTROLLER.md §17) against a real broker.

Skipped when no broker is on 127.0.0.1:1883. Proves, end to end: retained
status=online, a hello.echo round-trip with plausible skew, and status=offline on a
clean stop (the LWT covers the crash case, which a unit test cannot force cleanly)."""

import json
import socket
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

from controller.bridge.client import StationClient
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
    """A second MQTT client standing in for the app: watches status + collects replies."""

    def __init__(self, station):
        self.station = station
        self.status = None
        self.replies = {}
        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"probe-{uuid.uuid4().hex[:6]}", protocol=mqtt.MQTTv311)
        self._c.on_message = self._on_message
        self._c.connect(HOST, PORT, 30)
        self._c.subscribe(f"tmf/{station}/status", qos=1)
        self._c.subscribe(f"tmf/{station}/cmd/resp/probe", qos=1)
        self._c.loop_start()

    def _on_message(self, c, u, m):
        if m.topic.endswith("/status"):
            self.status = json.loads(m.payload).get("state")
        else:
            p = json.loads(m.payload)
            self.replies[p.get("id")] = p

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

    def wait_status(self, want, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.status == want:
                return True
            time.sleep(0.02)
        return False

    def close(self):
        self._c.loop_stop()
        self._c.disconnect()


def test_c1_status_and_hello_echo():
    station = f"ct_it_{uuid.uuid4().hex[:6]}"
    probe = _Probe(station)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    try:
        client.start()
        assert client.wait_connected(5.0)
        # 1. retained status online (acceptance §17.2)
        assert probe.wait_status("online", 5.0), "status did not go online"
        # 2. hello.echo round-trips with plausible skew (acceptance §17.4)
        sent = time.time()
        reply = probe.request("hello.echo", {"nonce": "n1", "sent_ts": sent})
        assert reply["ok"] is True and reply["nonce"] == "n1"
        assert reply["controller"] == "python"
        assert abs(reply["ts"] - sent) < 5.0            # clock skew sane
        # 3. unknown op -> structured error, not silence
        err = probe.request("does.not.exist", {})
        assert err["ok"] is False and err["error"]["code"] == "unknown_op"
    finally:
        client.stop()
        # 4. clean stop flips status offline (LWT covers the crash case)
        assert probe.wait_status("offline", 5.0), "status did not go offline"
        probe.close()

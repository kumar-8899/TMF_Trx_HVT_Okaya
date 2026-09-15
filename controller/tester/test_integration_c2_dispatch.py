"""Issue 2 fix — non-blocking command dispatch (PYTHON_CONTROLLER.md §3.4), live acceptance.

Skipped when no broker. Proves the paho network thread is never frozen by a hardware op:
a slow `instrument.call` in flight must not delay a concurrent `hello.echo`, a concurrent
`instrument.status` read, or a concurrent call to a *different* instrument — while calls to
the SAME instrument still serialize on its per-instance lock. Also proves `stop()` returns
promptly with a slow call still in flight (the dispatch pool is daemon-backed)."""

import json
import socket
import threading
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

_MAP = {"signals": {}, "actions": {}}


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
        self.replies = {}
        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"probe-{uuid.uuid4().hex[:6]}", protocol=mqtt.MQTTv311)
        self._c.on_message = self._on_message
        self._c.connect(HOST, PORT, 30)
        self._c.subscribe(f"tmf/{station}/cmd/resp/probe", qos=1)
        self._c.loop_start()

    def _on_message(self, c, u, m):
        p = json.loads(m.payload)
        self.replies[p.get("id")] = (p, time.time())

    def send(self, op, args):
        """Publish without waiting; returns the request id."""
        rid = uuid.uuid4().hex
        self._c.publish(f"tmf/{self.station}/cmd/{op}",
                        json.dumps({"id": rid, "op": op, "args": args,
                                    "reply_to": f"tmf/{self.station}/cmd/resp/probe"}), qos=1)
        return rid

    def request(self, op, args, timeout=5.0):
        rid = self.send(op, args)
        return self.wait(rid, timeout)

    def wait(self, rid, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if rid in self.replies:
                return self.replies[rid]
            time.sleep(0.01)
        raise AssertionError(f"no reply for request {rid}")

    def close(self):
        self._c.loop_stop()
        self._c.disconnect()


@pytest.fixture
def rig():
    lib = _fakelib.ensure_registered()
    station = f"c2disp_{uuid.uuid4().hex[:6]}"
    loop = AsyncLoopThread()
    loop.start()
    registry = InstrumentRegistry(loop)
    registry.build([
        {"id": "psu1", "library": lib, "simulated": True, "params": {"resource": "A"}},
        {"id": "psu2", "library": lib, "simulated": True, "params": {"resource": "B"}},
    ])
    loop.run(registry.connect_all())

    probe = _Probe(station)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    register_station_ops(client, StationVariables(station, _MAP, registry, loop), registry, loop)
    client.start()
    assert client.wait_connected(5.0)
    try:
        yield probe, client
    finally:
        client.stop()
        loop.run(registry.disconnect_all())
        loop.stop()
        probe.close()


def test_slow_instrument_call_does_not_delay_hello_echo(rig):
    probe, _ = rig
    slow_rid = probe.send("instrument.call", {"instance_id": "psu1", "method": "slow_op",
                                              "args": [1.5]})
    time.sleep(0.1)                                 # let the slow call actually start
    t0 = time.time()
    echo, echo_t = probe.wait(probe.send("hello.echo", {"nonce": "n1"}), timeout=3.0)
    assert echo["ok"] is True
    assert echo_t - t0 < 1.0, "hello.echo was queued behind the slow instrument call"

    slow, _ = probe.wait(slow_rid, timeout=3.0)
    assert slow["ok"] is True and slow["result"]["slept"] == 1.5


def test_slow_instrument_call_does_not_delay_a_different_instrument(rig):
    probe, _ = rig
    slow_rid = probe.send("instrument.call", {"instance_id": "psu1", "method": "slow_op",
                                              "args": [1.5]})
    time.sleep(0.1)
    t0 = time.time()
    other, other_t = probe.wait(
        probe.send("instrument.call", {"instance_id": "psu2", "method": "measure_voltage"}),
        timeout=3.0)
    assert other["ok"] is True and other["result"] == 5.0
    assert other_t - t0 < 1.0, "a different instrument's call was blocked by psu1's slow call"

    probe.wait(slow_rid, timeout=3.0)


def test_instrument_status_stays_instant_during_a_slow_call(rig):
    probe, _ = rig
    slow_rid = probe.send("instrument.call", {"instance_id": "psu1", "method": "slow_op",
                                              "args": [1.5]})
    time.sleep(0.1)
    t0 = time.time()
    status, status_t = probe.wait(probe.send("instrument.status", {}), timeout=3.0)
    assert status["ok"] is True
    assert status_t - t0 < 1.0, "instrument.status was queued behind the slow instrument call"

    probe.wait(slow_rid, timeout=3.0)


def test_same_instrument_calls_still_serialize(rig):
    probe, _ = rig
    t0 = time.time()
    rid_a = probe.send("instrument.call", {"instance_id": "psu1", "method": "slow_op",
                                           "args": [0.6]})
    rid_b = probe.send("instrument.call", {"instance_id": "psu1", "method": "slow_op",
                                           "args": [0.6]})
    a, ta = probe.wait(rid_a, timeout=5.0)
    b, tb = probe.wait(rid_b, timeout=5.0)
    assert a["ok"] is True and b["ok"] is True
    # Same instrument's per-instance lock still serializes: both together take ~2x one call,
    # not ~1x — proving they did NOT run concurrently against the same instrument.
    assert max(ta, tb) - t0 > 1.1, "same-instrument calls ran concurrently instead of serializing"


def test_stop_returns_promptly_with_a_slow_call_in_flight(rig):
    """stop()'s own network-loop teardown has an inherent ~1s baseline (paho's loop_stop);
    the point here is that it does NOT additionally wait out the hardware call — a slow_op
    that would take 3s must not push stop() anywhere near 3s+baseline."""
    probe, client = rig
    probe.send("instrument.call", {"instance_id": "psu1", "method": "slow_op", "args": [3.0]})
    time.sleep(0.1)
    t0 = time.time()
    done = threading.Event()

    def _stop():
        client.stop()
        done.set()

    t = threading.Thread(target=_stop, daemon=True)
    t.start()
    assert done.wait(2.0), "stop() did not return promptly with a hung call in flight"
    assert time.time() - t0 < 2.0

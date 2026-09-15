"""instrument.call / instrument.status — the backend-proxy bridge verbs added for the
single-client-instrument race fix (PYTHON_CONTROLLER.md; backend/modules/variables/instances.py
module docstring). Unit-level: no broker — calls the registered handlers directly against a
fake client capturing them (mirrors the backend's FakeBridge test pattern)."""

import pytest

from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import StationVariables
from controller.loop import AsyncLoopThread
from controller.serve import register_station_ops
from tester import _fakelib

_MAP = {"signals": {}, "actions": {}}


class FakeClient:
    def __init__(self):
        self.served: dict = {}

    def serve(self, op, handler, *, blocking=False):
        self.served[op] = handler

    def publish(self, topic, payload, *, retain=False):
        pass


@pytest.fixture
def rig():
    lib = _fakelib.ensure_registered()
    loop = AsyncLoopThread()
    loop.start()
    registry = InstrumentRegistry(loop)
    registry.build([{"id": "psu1", "library": lib, "simulated": True, "params": {}}])
    loop.run(registry.connect_all())
    client = FakeClient()
    register_station_ops(client, StationVariables("st1", _MAP, registry, loop), registry, loop)
    yield client, registry
    loop.run(registry.disconnect_all())
    loop.stop()


def test_instrument_call_happy_path(rig):
    client, _ = rig
    out = client.served["instrument.call"]({"instance_id": "psu1", "method": "measure_voltage"})
    assert out == {"ok": True, "result": 5.0}


def test_instrument_call_reaches_a_write_method(rig):
    client, registry = rig
    out = client.served["instrument.call"](
        {"instance_id": "psu1", "method": "set_voltage", "args": [12.5]})
    assert out["ok"] is True
    assert ("set_voltage", 12.5) in registry.get("psu1").transport.writes


def test_instrument_call_unknown_instance_is_not_connected(rig):
    client, _ = rig
    out = client.served["instrument.call"]({"instance_id": "nope", "method": "measure_voltage"})
    assert out["ok"] is False and out["error"]["code"] == "NotConnected"


def test_instrument_call_unknown_method_is_not_supported(rig):
    client, _ = rig
    out = client.served["instrument.call"]({"instance_id": "psu1", "method": "not_a_method"})
    assert out["ok"] is False and out["error"]["code"] == "NotSupported"


def test_instrument_call_missing_args_is_not_supported(rig):
    client, _ = rig
    out = client.served["instrument.call"]({"instance_id": "psu1"})
    assert out["ok"] is False and out["error"]["code"] == "NotSupported"


def test_instrument_call_disconnected_instance_is_not_connected(rig):
    client, registry = rig
    registry.get("psu1").state = "disconnected"
    out = client.served["instrument.call"]({"instance_id": "psu1", "method": "measure_voltage"})
    assert out["ok"] is False and out["error"]["code"] == "NotConnected"


def test_instrument_status_all_and_filtered(rig):
    client, _ = rig
    out = client.served["instrument.status"]({})
    rows = {r["id"]: r for r in out["result"]["instances"]}
    assert rows["psu1"]["state"] == "connected" and rows["psu1"]["simulated"] is True

    only = client.served["instrument.status"]({"ids": ["psu1", "nope"]})
    assert {r["id"] for r in only["result"]["instances"]} == {"psu1"}

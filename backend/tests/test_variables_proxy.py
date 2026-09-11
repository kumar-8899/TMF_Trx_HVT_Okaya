"""ProxiedInstrument + proxy-mode InstanceRegistry.build() — the single-client-instrument
race fix (backend/modules/variables/instances.py). Under controller.kind=="python" the
backend must never open its own connection to an owner=python instrument; every call
proxies through the controller's bridge verbs (instrument.call/instrument.status) instead.
No broker: a fake bridge stands in for core.services.bridge.
"""

from __future__ import annotations

import pytest

from core.services.bridge import BridgeError, BridgeTimeout
from core.services.diagnostics import Diagnostics
from instrumentlib import InstrumentBase, IPowerSource, instrument_library
from instrumentlib.errors import CommandTimeout, DeviceError, InstrumentError, NotConnected, NotSupported
from modules.variables.instances import DoubleOpenError, InstanceRegistry, ProxiedInstrument


@instrument_library(
    library_id="proxytest_supply", vendor="T", model="PS", capabilities=["power_source"],
    interface_version=1, transports=["sim"], library_version="1.0.0",
    generated_by="test", manual_reference="none",
)
class _ProxyTestSupply(InstrumentBase, IPowerSource):
    async def measure_current(self):
        return 1.0

    async def get_voltage_setpoint(self):
        return 1.0

    async def set_voltage(self, volts):
        pass


def _diag():
    return Diagnostics("st1", "0.0.0", sinks=[lambda e: None])


class FakeBridge:
    """Records the last request and returns a queued reply (or raises a queued exception)."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.reply: dict | None = None
        self.raise_: Exception | None = None

    async def request(self, op, args, *, station, timeout=None):
        self.calls.append((op, args, station, timeout))
        if self.raise_ is not None:
            raise self.raise_
        return self.reply


# --------------------------------------------------------------------- ProxiedInstrument


async def test_invoke_success_returns_the_result():
    bridge = FakeBridge()
    bridge.reply = {"ok": True, "result": 3.3}
    inst = ProxiedInstrument("psu1", library="proxytest_supply", capabilities=["power_source"],
                             simulated=False, bridge=bridge, station="st1")
    out = await inst.invoke("measure_voltage")
    assert out == 3.3
    op, args, station, _ = bridge.calls[0]
    assert op == "instrument.call" and station == "st1"
    assert args == {"instance_id": "psu1", "method": "measure_voltage", "args": []}


async def test_invoke_passes_args_through():
    bridge = FakeBridge()
    bridge.reply = {"ok": True, "result": None}
    inst = ProxiedInstrument("psu1", library="proxytest_supply", capabilities=[],
                             simulated=False, bridge=bridge, station="st1")
    await inst.invoke("set_voltage", 12.5)
    assert bridge.calls[0][1]["args"] == [12.5]


@pytest.mark.parametrize("code, cls", [
    ("NotConnected", NotConnected),
    ("NotSupported", NotSupported),
    ("DeviceError", DeviceError),
    ("CommandTimeout", CommandTimeout),
])
async def test_invoke_reconstructs_the_matching_exception(code, cls):
    bridge = FakeBridge()
    bridge.reply = {"ok": False, "error": {"code": code, "message": "boom", "detail": "d"}}
    inst = ProxiedInstrument("psu1", library="l", capabilities=[], simulated=False,
                             bridge=bridge, station="st1")
    with pytest.raises(cls) as ei:
        await inst.invoke("measure_voltage")
    assert ei.value.code == code and ei.value.detail == "d"


async def test_invoke_unrecognized_code_falls_back_to_instrument_error():
    bridge = FakeBridge()
    bridge.reply = {"ok": False, "error": {"code": "SomeWeirdCode", "message": "boom"}}
    inst = ProxiedInstrument("psu1", library="l", capabilities=[], simulated=False,
                             bridge=bridge, station="st1")
    with pytest.raises(InstrumentError) as ei:
        await inst.invoke("measure_voltage")
    assert not isinstance(ei.value, (NotConnected, NotSupported, DeviceError, CommandTimeout))


async def test_invoke_bridge_timeout_maps_to_not_connected():
    bridge = FakeBridge()
    bridge.raise_ = BridgeTimeout("no reply")
    inst = ProxiedInstrument("psu1", library="l", capabilities=[], simulated=False,
                             bridge=bridge, station="st1")
    with pytest.raises(NotConnected):
        await inst.invoke("measure_voltage")


async def test_invoke_bridge_error_maps_to_not_connected():
    bridge = FakeBridge()
    bridge.raise_ = BridgeError("not connected to broker")
    inst = ProxiedInstrument("psu1", library="l", capabilities=[], simulated=False,
                             bridge=bridge, station="st1")
    with pytest.raises(NotConnected):
        await inst.invoke("measure_voltage")


# ------------------------------------------------------------------ InstanceRegistry


async def test_build_with_bridge_produces_proxies_that_never_connect():
    reg = InstanceRegistry(_diag())
    bridge = FakeBridge()
    reg.build([{"id": "psu1", "library": "proxytest_supply", "simulated": True}],
             bridge=bridge, station="st1")
    inst = reg.get("psu1")
    assert isinstance(inst, ProxiedInstrument)
    await reg.connect_all()   # must be a no-op — never touch the bridge
    assert bridge.calls == []
    assert inst.state == "disconnected"   # unrefreshed until a live status poll


async def test_build_without_bridge_is_unchanged_direct_connect():
    reg = InstanceRegistry(_diag())
    reg.build([{"id": "psu1", "library": "proxytest_supply", "simulated": True}])
    assert not isinstance(reg.get("psu1"), ProxiedInstrument)
    await reg.connect_all()
    assert reg.get("psu1").state == "connected"


async def test_double_open_guard_still_applies_when_not_proxied():
    reg = InstanceRegistry(_diag())
    with pytest.raises(DoubleOpenError):
        reg.build([
            {"id": "a", "library": "proxytest_supply", "params": {"ip": "1.1.1.1"}},
            {"id": "b", "library": "proxytest_supply", "params": {"ip": "1.1.1.1"}},
        ])


async def test_double_open_guard_does_not_apply_to_proxied_instances():
    reg = InstanceRegistry(_diag())
    bridge = FakeBridge()
    # same resource params, but proxy mode never opens anything locally — no collision to guard
    reg.build([
        {"id": "a", "library": "proxytest_supply", "params": {"ip": "1.1.1.1"}},
        {"id": "b", "library": "proxytest_supply", "params": {"ip": "1.1.1.1"}},
    ], bridge=bridge, station="st1")
    assert isinstance(reg.get("a"), ProxiedInstrument) and isinstance(reg.get("b"), ProxiedInstrument)


async def test_status_reports_per_instance_declaration_for_proxies():
    reg = InstanceRegistry(_diag())
    bridge = FakeBridge()
    reg.build([{"id": "psu1", "library": "proxytest_supply", "simulated": True}],
             bridge=bridge, station="st1")
    st = {s["id"]: s for s in reg.status()}
    assert st["psu1"]["library"] == "proxytest_supply"
    assert st["psu1"]["capabilities"] == ["power_source"]
    assert st["psu1"]["state"] == "disconnected"


async def test_refresh_proxied_status_updates_state_from_the_controller():
    reg = InstanceRegistry(_diag())
    bridge = FakeBridge()
    reg.build([{"id": "psu1", "library": "proxytest_supply", "simulated": True},
              {"id": "psu2", "library": "proxytest_supply", "simulated": True}],
             bridge=bridge, station="st1")
    bridge.reply = {"ok": True, "result": {"instances": [
        {"id": "psu1", "state": "connected", "simulated": True, "library": "proxytest_supply"},
        {"id": "psu2", "state": "faulted", "simulated": True, "library": "proxytest_supply"},
    ]}}
    await reg.refresh_proxied_status()
    assert reg.get("psu1").state == "connected"
    assert reg.get("psu2").state == "faulted"
    op, args, station, _ = bridge.calls[0]
    assert op == "instrument.status" and set(args["ids"]) == {"psu1", "psu2"} and station == "st1"


async def test_refresh_proxied_status_is_best_effort_on_bridge_failure():
    reg = InstanceRegistry(_diag())
    bridge = FakeBridge()
    bridge.raise_ = BridgeTimeout("controller not up yet")
    reg.build([{"id": "psu1", "library": "proxytest_supply", "simulated": True}],
             bridge=bridge, station="st1")
    await reg.refresh_proxied_status()   # must not raise
    assert reg.get("psu1").state == "disconnected"   # unchanged, not crashed


async def test_refresh_proxied_status_is_a_noop_without_proxies():
    reg = InstanceRegistry(_diag())
    reg.build([{"id": "psu1", "library": "proxytest_supply", "simulated": True}])
    await reg.refresh_proxied_status()   # no bridge configured at all — must not raise

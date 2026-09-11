"""variables standalone tester — engine + instance registry + bridge seam.

Registers a SIM power-source library as the subject (product libraries live in the
separate library repo). No broker; :memory: db.
"""

import pytest

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from instrumentlib import InstrumentBase, IPowerSource, instrument_library
from modules.variables.engine import VariableError
from modules.variables.instances import DoubleOpenError, InstanceRegistry
from modules.variables.variants.default import DefaultVariables


@instrument_library(
    library_id="vtest_supply", vendor="T", model="PS", capabilities=["power_source"],
    interface_version=1, transports=["sim"], library_version="1.0.0",
    generated_by="test", manual_reference="none",
)
class VTestSupply(InstrumentBase, IPowerSource):
    CMD = {"set_v": "VOLT {v}", "get_v": "VOLT?", "meas_i": "MEAS:CURR?"}

    async def measure_current(self):
        return float(await self.transport.query(self.CMD["meas_i"]))   # sim -> 1.0

    async def get_voltage_setpoint(self):
        return float(await self.transport.query(self.CMD["get_v"]))    # sim -> 1.0

    async def set_voltage(self, volts):
        await self.transport.write(self.CMD["set_v"].format(v=volts))


class FakeBridge:
    online = True
    station = "st1"

    def __init__(self):
        self.served: dict = {}
        self.requests: list = []      # (op, args, station) — proxy-mode calls, if any
        self.reply: dict | None = None

    def serve(self, op, handler):
        self.served[op] = handler

    async def request(self, op, args, *, station, timeout=None):
        self.requests.append((op, args, station))
        return self.reply


def _cfg():
    return {
        "instances": [{"id": "load_1", "library": "vtest_supply", "simulated": True}],
        "variables": {
            "out_current": {"instance": "load_1", "read": "measure_current",
                            "scale": {"gain": 2.0, "offset": 1.0}, "units": "A"},
            "dc_setpoint": {"instance": "load_1", "write": "set_voltage",
                            "read": "get_voltage_setpoint", "clamp": {"min": 0.0, "max": 400.0}, "units": "V"},
            "orphan": {"instance": "missing", "read": "measure_voltage"},
        },
    }


@pytest.fixture
async def mod():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    bridge = FakeBridge()
    core = CoreServices(db=db, bridge=bridge,
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    m = DefaultVariables.construct(core, _cfg())
    await m.start()          # connects instances + registers bridge verbs
    yield m, bridge
    await m.stop()
    await db.close()


async def test_read_applies_scale(mod):
    m, _ = mod
    r = await m.engine.read("out_current")
    assert r["raw"] == 1.0 and r["value"] == 3.0 and r["units"] == "A"   # 1*2+1


async def test_write_clamps_and_inverse_scales(mod):
    m, _ = mod
    r = await m.engine.write("dc_setpoint", 500)
    assert r["written"] == 400.0 and r["clamped"] is True
    inst = m.instances.get("load_1")
    assert "VOLT 400.0" in inst.transport.writes
    lo = await m.engine.write("dc_setpoint", -5)
    assert lo["written"] == 0.0 and lo["clamped"] is True


async def test_direction_and_unknown_errors(mod):
    m, _ = mod
    with pytest.raises(VariableError):
        await m.engine.read("nope")                # unknown
    with pytest.raises(VariableError):
        await m.engine.write("out_current", 1)     # read-only variable


async def test_unbound_and_list(mod):
    m, _ = mod
    assert m.engine.unbound() == ["st1:orphan"]    # instance 'missing' not loaded (station:name)
    names = {v["name"]: v for v in m.engine.list()}
    assert names["out_current"]["bound"] is True and names["orphan"]["bound"] is False
    assert await m.ready() is False                # unbound blocks readiness


async def test_bridge_serves_variable_verbs(mod):
    m, bridge = mod
    assert set(bridge.served) == {"variable.read", "variable.write", "variable.read_many",
                                  "variable.write_many", "capability.request"}
    out = await bridge.served["variable.read"]({"name": "out_current"})
    assert out["value"] == 3.0


async def test_capability_request_bypasses_the_engine(mod):
    m, bridge = mod
    # non-scalar seam: call a method on an instance by id (here a scalar read, for the test)
    out = await m.call("load_1", "measure_current")
    assert out["instance"] == "load_1" and out["result"] == 1.0
    via_bus = await bridge.served["capability.request"]({"instance": "load_1", "method": "measure_current"})
    assert via_bus["result"] == 1.0
    with pytest.raises(VariableError):
        await m.call("missing", "measure_current")


async def test_libraries_and_instance_status(mod):
    m, _ = mod
    libs = {l["library_id"] for l in m.libraries()["libraries"]}
    assert "vtest_supply" in libs
    st = {s["id"]: s for s in m.instance_status()}
    assert st["load_1"]["state"] == "connected" and st["load_1"]["library"] == "vtest_supply"
    assert st["load_1"]["capabilities"] == ["power_source"]   # panel maps instance -> capability


async def test_capabilities_catalog(mod):
    m, _ = mod
    cat = m.capabilities()
    assert "power_source" in cat["capabilities"]
    ps = {x["method"]: x for x in cat["capabilities"]["power_source"]["methods"]}
    # every scalar interface method is described (drift assert also enforces this on import)
    from instrumentlib.interfaces import IPowerSource
    assert set(ps) == set(IPowerSource.METHODS)
    assert ps["set_voltage"]["kind"] == "set" and ps["set_voltage"]["args"][0]["name"] == "volts"
    assert ps["output_enable"]["kind"] == "toggle"
    assert ps["measure_voltage"]["kind"] == "read"
    assert {b["method"] for b in cat["base_actions"]} == {"safe_state", "emergency_disable"}


async def test_instances_sourced_from_config_module():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=None,
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")

    class _FakeConfig:
        async def python_instruments(self):
            return [{"id": "cfg_psu", "library": "vtest_supply", "simulated": True, "params": {}}]

    def _get(name):
        if name == "config":
            return _FakeConfig()
        raise KeyError(name)
    object.__setattr__(core, "get_contract", _get)

    m = DefaultVariables.construct(core, {"variables": {
        "cfg_v": {"instance": "cfg_psu", "read": "measure_current", "units": "A"}}})
    await m.start()
    assert any(s["id"] == "cfg_psu" for s in m.instance_status())   # built from the config module
    assert (await m.engine.read("cfg_v"))["value"] == 1.0
    await m.stop(); await db.close()


async def test_library_import_is_loud_but_nonfatal():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=None,
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    # a bad package name must not crash construction (logged + skipped)
    m = DefaultVariables.construct(core, {"library_packages": ["nonexistent_pkg_zzz"],
                                          "instances": [], "variables": {}})
    assert m.instance_status() == []
    await db.close()


def test_double_open_guard():
    reg = InstanceRegistry(Diagnostics("st1", "0.0.0", sinks=[lambda e: None]))
    with pytest.raises(DoubleOpenError):
        reg.build([
            {"id": "a", "library": "vtest_supply", "params": {"ip": "1.1.1.1"}},
            {"id": "b", "library": "vtest_supply", "params": {"ip": "1.1.1.1"}},
        ])


def test_unknown_library_skipped_not_fatal():
    reg = InstanceRegistry(Diagnostics("st1", "0.0.0", sinks=[lambda e: None]))
    reg.build([{"id": "x", "library": "does_not_exist"}])
    assert reg.all() == [] and reg.skipped[0]["library"] == "does_not_exist"


# --- single-client-instrument race fix: controller.kind=="python" proxies instances ----


async def test_controller_kind_python_proxies_instead_of_connecting_directly():
    from modules.variables.instances import ProxiedInstrument

    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    bridge = FakeBridge()
    core = CoreServices(db=db, bridge=bridge, controller_kind="python",
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    m = DefaultVariables.construct(core, {"instances": [
        {"id": "load_1", "library": "vtest_supply", "simulated": True}], "variables": {}})
    await m.start()
    inst = m.instances.get("load_1")
    assert isinstance(inst, ProxiedInstrument)          # never the real driver class
    assert bridge.requests == []                        # connect_all() touched nothing
    assert m.instance_status()[0]["state"] == "disconnected"   # unrefreshed until asked

    bridge.reply = {"ok": True, "result": {"instances": [
        {"id": "load_1", "state": "connected", "simulated": True, "library": "vtest_supply"}]}}
    await m.refresh_instance_status()
    assert m.instance_status()[0]["state"] == "connected"
    op, args, station = bridge.requests[0]
    assert op == "instrument.status" and args["ids"] == ["load_1"] and station == "st1"
    await m.stop()
    await db.close()


async def test_controller_kind_labview_connects_directly_unchanged():
    """Regression guard: without a supervised Python controller there is nothing to proxy
    through, and owner=python instruments must keep connecting directly, exactly as before."""
    from modules.variables.instances import ProxiedInstrument

    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=FakeBridge(), controller_kind="labview",
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    m = DefaultVariables.construct(core, {"instances": [
        {"id": "load_1", "library": "vtest_supply", "simulated": True}], "variables": {}})
    await m.start()
    inst = m.instances.get("load_1")
    assert not isinstance(inst, ProxiedInstrument)
    assert m.instance_status()[0]["state"] == "connected"
    await m.stop()
    await db.close()

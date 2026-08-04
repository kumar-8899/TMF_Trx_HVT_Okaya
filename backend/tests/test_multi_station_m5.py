"""M5 — config instrument stations[] + variables per-station maps + the shared-instrument
no-lease rule (MULTI_STATION.md §4.2/§4.3, PYTHON_CONTROLLER.md §9.3)."""

import types

import pytest

from core.services.db import Database
from modules.variables import bindings
from modules.variables.variants.default import DefaultVariables


class _Diag:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


@pytest.fixture
async def module():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = types.SimpleNamespace(diag=_Diag(), db=types.SimpleNamespace(repo=db.repo),
                                 bridge=None, get_contract=None,
                                 stations=["st1", "st2"], station="st1")
    mod = DefaultVariables(core, {"variables": {}})
    # two instruments: a per-station PSU (one per socket) + a DAQ shared across both.
    mod.instance_status = lambda: [
        {"id": "psu_st1", "capabilities": ["power_source"], "state": "connected"},
        {"id": "psu_st2", "capabilities": ["power_source"], "state": "connected"},
        {"id": "daq_shared", "capabilities": ["analog_input"], "state": "connected"},
    ]
    mod._instance_stations = {"psu_st1": ["st1"], "psu_st2": ["st2"],
                              "daq_shared": ["st1", "st2"]}
    yield mod
    await db.close()


async def test_same_name_binds_different_instance_per_station(module):
    await module.save_binding("supply_v", {"instance": "psu_st1", "read": "measure_voltage",
                                           "write": "set_voltage", "station": "st1"}, is_new=True)
    await module.save_binding("supply_v", {"instance": "psu_st2", "read": "measure_voltage",
                                           "write": "set_voltage", "station": "st2"}, is_new=True)
    st1 = {v["name"]: v for v in module.list_bindings("st1")}
    st2 = {v["name"]: v for v in module.list_bindings("st2")}
    assert st1["supply_v"]["instance"] == "psu_st1"      # same name…
    assert st2["supply_v"]["instance"] == "psu_st2"      # …different socket, different device


async def test_default_station_when_omitted(module):
    # single-station front end omits station -> resolves to the first socket
    await module.save_binding("v", {"instance": "psu_st1", "read": "measure_voltage"}, is_new=True)
    assert "v" in module.engine.map_for("st1") and "v" not in module.engine.map_for("st2")


async def test_shared_instrument_read_only_allowed(module):
    rec = await module.save_binding("amb", {"instance": "daq_shared", "read": "read_voltage",
                                            "args": [0], "station": "st1"}, is_new=True)
    assert rec["station"] == "st1"


async def test_shared_instrument_write_refused(module):
    # daq_shared spans st1+st2 -> a write binding is the silent-wrong-PASS hazard, refused
    with pytest.raises(bindings.BindingError):
        await module.save_binding("bad", {"instance": "daq_shared", "write": "set_voltage",
                                          "station": "st1"}, is_new=True)


async def test_bindable_hides_write_for_shared(module):
    b = module.bindable("daq_shared")
    assert b["shared"] is True and b["write"] == []
    solo = module.bindable("psu_st1")
    assert solo["shared"] is False and any(m["method"] == "set_voltage" for m in solo["write"])


async def test_unknown_station_rejected(module):
    with pytest.raises(bindings.BindingError):
        await module.save_binding("v", {"instance": "psu_st1", "read": "measure_voltage",
                                        "station": "st9"}, is_new=True)

"""Variable-map editor — binding rules + DB-backed CRUD with live hot-apply.

The rules layer (bindings.py) derives bindable methods from a library's declared
capabilities and validates a binding; the variant persists it as a DB record and
applies it to the live engine map without a restart.
"""

import types

import pytest

from core.services.db import Database
from modules.variables import bindings
from modules.variables.variants.default import BindingUnknownInstance, DefaultVariables


# ---- rules (pure) ---------------------------------------------------------

def test_bindable_derives_from_capabilities():
    b = bindings.bindable_for(["power_source"])
    reads = {m["method"] for m in b["read"]}
    writes = {m["method"] for m in b["write"]}
    assert "measure_voltage" in reads and "measure_current" in reads
    assert "set_voltage" in writes and "set_current_limit" in writes
    # toggle (output_enable) + enum are NOT numeric-bindable
    assert "output_enable" not in writes


def test_bindable_channel_read_carries_fixed_arg():
    b = bindings.bindable_for(["temperature"])
    m = next(m for m in b["read"] if m["method"] == "measure_temperature")
    assert [a["name"] for a in m["fixed_args"]] == ["channel"]


def test_validate_setpoint_no_fixed_args():
    rec = bindings.validate("cell_v", {"instance": "psu1", "read": "measure_voltage",
                                       "write": "set_voltage", "units": "V",
                                       "scale": {"gain": 2.0}}, ["power_source"])
    assert rec == {"instance": "psu1", "args": [], "read": "measure_voltage",
                   "write": "set_voltage", "units": "V", "scale": {"gain": 2.0, "offset": 0.0}}


def test_validate_channel_arg_coerced_to_int():
    rec = bindings.validate("t1", {"instance": "dmm", "read": "measure_temperature",
                                   "args": ["3"]}, ["temperature"])
    assert rec["args"] == [3] and rec["units"] == "°"


def test_validate_rejects_bad_name():
    with pytest.raises(bindings.BindingError):
        bindings.validate("Bad Name", {"instance": "x", "read": "measure_voltage"}, ["power_source"])


def test_validate_rejects_method_not_on_instrument():
    with pytest.raises(bindings.BindingError):
        bindings.validate("x", {"instance": "psu1", "read": "measure_temperature"}, ["power_source"])


def test_validate_requires_a_direction():
    with pytest.raises(bindings.BindingError):
        bindings.validate("x", {"instance": "psu1"}, ["power_source"])


def test_validate_rejects_wrong_arg_count():
    with pytest.raises(bindings.BindingError):
        bindings.validate("t", {"instance": "d", "read": "measure_temperature", "args": []},
                          ["temperature"])


def test_validate_rejects_inverted_clamp():
    with pytest.raises(bindings.BindingError):
        bindings.validate("v", {"instance": "p", "write": "set_voltage",
                                "clamp": {"min": 5, "max": 1}}, ["power_source"])


# ---- variant CRUD + hot-apply ---------------------------------------------

class _Diag:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


@pytest.fixture
async def module():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = types.SimpleNamespace(diag=_Diag(), db=types.SimpleNamespace(repo=db.repo),
                                 bridge=None, get_contract=None)
    mod = DefaultVariables(core, {"variables": {}})
    # pretend one power source is live (bypass real hardware build)
    mod.instance_status = lambda: [
        {"id": "psu1", "library": "acme_psu", "capabilities": ["power_source"],
         "state": "connected", "simulated": True}]
    yield mod
    await db.close()


async def test_bindable_endpoint_shape(module):
    b = module.bindable("psu1")
    assert b["instance"] == "psu1" and "power_source" in b["capabilities"]
    assert {m["method"] for m in b["write"]} >= {"set_voltage", "set_current_limit"}


async def test_bindable_unknown_instance_raises(module):
    with pytest.raises(BindingUnknownInstance):
        module.bindable("nope")


async def test_save_lists_persists_and_hot_applies(module):
    rec = await module.save_binding("cell_v", {"instance": "psu1", "read": "measure_voltage",
                                               "write": "set_voltage", "units": "V"}, is_new=True)
    assert rec["editable"] is True and rec["station"] == "st1"
    # applied live to the default station's map (no restart)
    assert module.engine.map_for("st1")["cell_v"]["read"] == "measure_voltage"
    # persisted as a DB record keyed station:name
    row = await module.core.db.repo.get("variable", "st1:cell_v")
    assert row["data"]["name"] == "cell_v" and row["data"]["station"] == "st1"
    listed = {v["name"]: v for v in module.list_bindings()}
    assert listed["cell_v"]["editable"] and listed["cell_v"]["bound"] is False


async def test_save_binding_unknown_instance_raises(module):
    with pytest.raises(BindingUnknownInstance):
        await module.save_binding("x", {"instance": "ghost", "read": "measure_voltage"}, is_new=True)


async def test_duplicate_create_rejected(module):
    await module.save_binding("v", {"instance": "psu1", "read": "measure_voltage"}, is_new=True)
    with pytest.raises(bindings.BindingError):
        await module.save_binding("v", {"instance": "psu1", "read": "measure_current"}, is_new=True)


async def test_delete_removes_binding(module):
    await module.save_binding("v", {"instance": "psu1", "read": "measure_voltage"}, is_new=True)
    assert await module.delete_binding("v") is True
    assert "v" not in module.engine.map_for("st1")
    assert await module.delete_binding("v") is False


async def test_db_binding_reloads_over_static(module):
    await module.save_binding("v", {"instance": "psu1", "read": "measure_voltage"}, is_new=True)
    # fresh engine maps, then reload from DB (simulates a restart)
    module.engine.maps = {"st1": {}}
    module._db_vars = set()
    await module._load_db_bindings()
    assert module.engine.map_for("st1")["v"]["read"] == "measure_voltage"
    assert "name" not in module.engine.map_for("st1")["v"]

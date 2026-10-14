"""D9 — a fresh install must be able to read the signals the app SHIPS.

The backend engine map used to be built only from app.json `variables` + DB bindings, so a UI read of
a signal that exists in `app/<slug>/maps/<station>.json` raised `unknown variable` until someone
re-authored it by hand. The supervisor records the shipped map's path (controller.maps/index.json,
docs/contracts/CALIBRATION.md); the engine now resolves names from it as a fallback."""

import json

import pytest

from core.framework.contract import CoreServices
from core.services import calibration as cal
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from instrumentlib import InstrumentBase, IPowerSource, instrument_library
from modules.variables.engine import VariableError
from modules.variables.variants.default import DefaultVariables


@instrument_library(
    library_id="shipped_supply", vendor="T", model="PS", capabilities=["power_source"],
    interface_version=1, transports=["sim"], library_version="1.0.0",
    generated_by="test", manual_reference="none",
)
class ShippedSupply(InstrumentBase, IPowerSource):
    async def measure_current(self):
        return float(await self.transport.query("MEAS:CURR?"))       # sim -> 1.0

    async def set_voltage(self, volts):
        await self.transport.write(f"VOLT {volts}")


SHIPPED = {"signals": {
    "door_closed": {"instance": "psu", "read": "measure_current", "units": ""},
    "cur": {"instance": "psu", "read": "measure_current", "scale": {"gain": 3.0, "offset": 0.0}},
    "ghost": {"instance": "not_configured", "read": "measure_current"},
}, "actions": {}}


async def _mod(tmp_path, *, variables=None, with_index=True, instances=True):
    d = tmp_path / "data"
    if with_index:
        ship = tmp_path / "maps" / "st1.json"
        ship.parent.mkdir(parents=True)
        ship.write_text(json.dumps(SHIPPED), encoding="utf-8")
        cal.write_index(d, {"st1": {"shipped": str(ship), "effective": str(d / "e.json"),
                                    "overlay": str(cal.overlay_path(d, "st1"))}})
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=None, controller_kind="labview", station="st1",
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]))
    cfg = {"data_dir": str(d), "variables": variables or {},
           "instances": [{"id": "psu", "library": "shipped_supply", "simulated": True}] if instances else []}
    m = DefaultVariables.construct(core, cfg)
    await m.start()
    return m, db


@pytest.fixture
async def fresh(tmp_path):
    m, db = await _mod(tmp_path)
    yield m
    await m.stop()
    await db.close()


async def test_fresh_install_reads_a_shipped_signal(fresh):
    r = await fresh.engine.read("door_closed")                     # no app.json variable, no DB binding
    assert r["raw"] == 1.0 and r["value"] == 1.0
    assert (await fresh.engine.read("cur"))["value"] == 3.0        # shipped scale honoured
    assert (await fresh.engine.read_many(["door_closed", "cur"]))["cur"]["value"] == 3.0


async def test_shipped_signals_are_listed_with_their_source(fresh):
    rows = {r["name"]: r for r in fresh.engine.list()}
    assert rows["door_closed"]["source"] == "shipped" and rows["door_closed"]["bound"] is True
    assert rows["ghost"]["bound"] is False                          # unreadable, and says so


async def test_unbound_shipped_signal_is_loud_on_read_but_never_blocks_readiness(fresh):
    with pytest.raises(Exception, match="not_configured"):
        await fresh.engine.read("ghost")                            # visible failure, not a silent default
    assert fresh.engine.unbound() == [] and await fresh.ready() is True


async def test_app_json_and_db_bindings_override_the_shipped_map(tmp_path):
    m, db = await _mod(tmp_path, variables={"cur": {"instance": "psu", "read": "measure_current",
                                                    "scale": {"gain": 10.0, "offset": 0.0}}})
    try:
        assert (await m.engine.read("cur"))["value"] == 10.0
        assert {r["name"]: r for r in m.engine.list()}["cur"].get("source") != "shipped"
    finally:
        await m.stop()
        await db.close()


async def test_calibration_overlay_applies_to_shipped_signals_too(fresh):
    await fresh.calibration.apply("cur", [{"raw": 0, "reference": 1.0}, {"raw": 2, "reference": 5.0}],
                                  None, "t")                         # 2x + 1
    assert (await fresh.engine.read("cur"))["value"] == pytest.approx(3.0)   # raw 1 -> 3


async def test_no_index_means_no_shipped_signals_and_unknown_still_raises(tmp_path):
    m, db = await _mod(tmp_path, with_index=False)
    try:
        with pytest.raises(VariableError):
            await m.engine.read("door_closed")
    finally:
        await m.stop()
        await db.close()


async def test_unreadable_shipped_map_is_loud_not_fatal(tmp_path):
    d = tmp_path / "data"
    cal.write_index(d, {"st1": {"shipped": str(tmp_path / "missing.json"), "effective": "", "overlay": ""}})
    events = []
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=None, station="st1",
                        diag=Diagnostics("st1", "0.0.0", sinks=[events.append]))
    m = DefaultVariables.construct(core, {"data_dir": str(d), "variables": {}, "instances": []})
    try:
        await m.start()
        assert any("shipped" in str(getattr(e, "message", e)).lower() for e in events)
    finally:
        await m.stop()
        await db.close()

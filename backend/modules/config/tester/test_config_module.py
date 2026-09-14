"""config standalone tester (CORE.md §6.2) — core + config, :memory: db."""

import pytest

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from instrumentlib import InstrumentBase, IPowerSource, instrument_library
from modules.config.variants.default import ConfigError, DefaultConfig


@instrument_library(
    library_id="ctest_supply", vendor="C", model="PS", capabilities=["power_source"],
    interface_version=1, transports=["visa_lan"],
    connection_params={"resource": {"type": "string"}, "timeout_ms": {"type": "int", "default": 5000}},
    library_version="1.0.0", generated_by="test", manual_reference="none",
)
class _CTestSupply(InstrumentBase, IPowerSource):
    pass


class FakeBridge:
    def __init__(self, online=True, reply=None):
        self._online = online
        self.reply = reply or {"ok": True, "identity": "ACME,DMM-1,1.0", "detail": "connected"}
        self.requests = []

    @property
    def online(self):
        return self._online

    async def request(self, op, args, *, station=None, timeout=None):
        self.requests.append((op, args))
        return self.reply


async def _build(bridge=None):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=bridge,
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    return DefaultConfig.construct(core, {}), core, db


@pytest.fixture
async def ctx():
    module, core, db = await _build(FakeBridge())
    yield module, core, db
    await db.close()


async def test_transports_catalog(ctx):
    module, _, _ = ctx
    ids = {t["id"] for t in module.transports()}
    assert {"visa", "modbus_tcp", "can", "nidaq"} <= ids
    visa = next(t for t in module.transports() if t["id"] == "visa")
    assert visa["fields"][0]["key"] == "resource" and visa["fields"][0]["required"]


def _ts(y, mo, d, h, mi):
    from datetime import datetime
    return datetime(y, mo, d, h, mi).timestamp()


async def test_shift_config_validation_and_sort(ctx):
    module, _, _ = ctx
    with pytest.raises(ConfigError):
        await module.set_shift_config({"enabled": True, "shifts": []})            # enabled needs shifts
    with pytest.raises(ConfigError):
        await module.set_shift_config({"enabled": True, "shifts": [{"label": "A", "start": "25:00"}]})
    cfg = await module.set_shift_config({"enabled": True, "shifts": [
        {"label": "Night", "start": "22:00"}, {"label": "Morning", "start": "06:00"},
        {"label": "Evening", "start": "14:00"}]})
    assert [s["start"] for s in cfg["shifts"]] == ["06:00", "14:00", "22:00"]      # sorted; first = boundary


async def test_shift_for_business_day_overnight(ctx):
    module, _, _ = ctx
    await module.set_shift_config({"enabled": True, "shifts": [
        {"label": "Morning", "start": "06:00"}, {"label": "Evening", "start": "14:00"},
        {"label": "Night", "start": "22:00"}]})
    # 02:00 Jul-5 is the Night shift that STARTED 22:00 Jul-4 -> business day Jul-4
    r = await module.shift_for(_ts(2026, 7, 5, 2, 0))
    assert r["shift_label"] == "Night" and r["business_day"] == "2026-07-04"
    r = await module.shift_for(_ts(2026, 7, 5, 8, 0))
    assert r["shift_label"] == "Morning" and r["business_day"] == "2026-07-05"
    r = await module.shift_for(_ts(2026, 7, 5, 22, 30))
    assert r["shift_label"] == "Night" and r["business_day"] == "2026-07-05"


async def test_shift_disabled_falls_back_to_calendar(ctx):
    module, _, _ = ctx
    r = await module.shift_for(_ts(2026, 7, 5, 2, 0))
    assert r["enabled"] is False and r["business_day"] == "2026-07-05" and r["shift_label"] is None


async def test_barcode_config_validation(ctx):
    module, _, _ = ctx
    with pytest.raises(ConfigError):
        await module.set_barcode_config({"length": 0})
    with pytest.raises(ConfigError):  # part start < 0
        await module.set_barcode_config({"length": 8, "parts": [{"name": "model", "start": -1, "length": 3}]})
    with pytest.raises(ConfigError):  # part length < 1
        await module.set_barcode_config({"length": 8, "parts": [{"name": "model", "start": 0, "length": 0}]})
    with pytest.raises(ConfigError):  # exceeds total length
        await module.set_barcode_config({"length": 5, "parts": [{"name": "model", "start": 0, "length": 8}]})
    with pytest.raises(ConfigError):  # duplicate names
        await module.set_barcode_config({"length": 8, "parts": [
            {"name": "model", "start": 0, "length": 3}, {"name": "model", "start": 3, "length": 5}]})
    with pytest.raises(ConfigError):  # enabled with no parts
        await module.set_barcode_config({"enabled": True, "length": 8, "parts": []})
    with pytest.raises(ConfigError):  # enabled, recipe_part doesn't reference a part
        await module.set_barcode_config({"enabled": True, "length": 8,
            "parts": [{"name": "model", "start": 0, "length": 3}], "recipe_part": "nope"})


async def test_barcode_config_round_trip(ctx):
    module, _, _ = ctx
    saved = await module.set_barcode_config({"enabled": True, "length": 8, "parts": [
        {"name": "model", "start": 0, "length": 3}, {"name": "serial", "start": 3, "length": 5}],
        "recipe_part": "model"})
    assert saved["enabled"] is True and saved["length"] == 8
    cfg = await module.get_barcode_config()
    assert cfg == {"enabled": True, "length": 8, "parts": [
        {"name": "model", "start": 0, "length": 3}, {"name": "serial", "start": 3, "length": 5}],
        "recipe_part": "model"}


async def test_resolve_recipe_from_barcode_disabled(ctx):
    module, _, _ = ctx
    out = await module.resolve_recipe_from_barcode("INV12345")
    assert out == {"ok": False, "error": "barcode acquisition not enabled"}


async def _enable(module, length=8, recipe_part="model"):
    await module.set_barcode_config({"enabled": True, "length": length, "parts": [
        {"name": "model", "start": 0, "length": 3}, {"name": "serial", "start": 3, "length": 5}],
        "recipe_part": recipe_part})


async def test_resolve_recipe_from_barcode_success(ctx):
    module, _, _ = ctx
    await _enable(module)
    out = await module.resolve_recipe_from_barcode("INV12345")
    assert out == {"ok": True, "recipe_id": "INV", "parts": {"model": "INV", "serial": "12345"}}


async def test_resolve_recipe_from_barcode_empty(ctx):
    module, _, _ = ctx
    await _enable(module)
    out = await module.resolve_recipe_from_barcode("   ")
    assert out == {"ok": False, "error": "empty barcode"}


async def test_resolve_recipe_from_barcode_wrong_length(ctx):
    module, _, _ = ctx
    await _enable(module)
    assert (await module.resolve_recipe_from_barcode("SHORT"))["ok"] is False
    assert (await module.resolve_recipe_from_barcode("WAYTOOLONG123"))["ok"] is False


async def test_resolve_recipe_from_barcode_no_recipe_part(ctx):
    module, _, _ = ctx
    # enabled + a valid recipe_part first (set_barcode_config requires it), then simulate
    # a stale reference by re-saving with a part rename — no recipe_part matches any more
    await _enable(module)
    rec = await module.get_barcode_config()
    rec["recipe_part"] = "does_not_exist"
    await module.core.db.repo.put("barcode_config", rec, id="barcode", summary="stale")
    out = await module.resolve_recipe_from_barcode("INV12345")
    assert out == {"ok": False, "error": "no recipe part configured"}


async def test_resolve_recipe_from_barcode_empty_extracted_value(ctx):
    module, _, _ = ctx
    # recipe part is a single space in the middle -> empty once stripped, but the overall
    # barcode itself has no leading/trailing whitespace (so it still passes the length check)
    await module.set_barcode_config({"enabled": True, "length": 5, "parts": [
        {"name": "model", "start": 2, "length": 1}], "recipe_part": "model"})
    out = await module.resolve_recipe_from_barcode("AB CD")
    assert out == {"ok": False, "error": "extracted recipe id is empty"}


async def test_instrument_stations_multi_and_migration():
    # M5: instruments carry stations[]; singular migrates; absent -> all sockets;
    # an unknown socket is rejected (MULTI_STATION.md §4.3).
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=FakeBridge(),
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]),
                        stations=["st1", "st2"], station="st1")
    module = DefaultConfig.construct(core, {})
    try:
        a = await module.create_instrument({"id": "load_a", "transport": "visa",
                                            "params": {"resource": "x"}, "stations": ["st2"]})
        assert a["stations"] == ["st2"]
        b = await module.create_instrument({"id": "load_b", "transport": "visa",
                                            "params": {"resource": "y"}, "station": "st1"})
        assert b["stations"] == ["st1"]                       # singular migrated
        c = await module.create_instrument({"id": "load_c", "transport": "visa",
                                            "params": {"resource": "z"}})
        assert c["stations"] == ["st1", "st2"]                # absent -> shared across all
        with pytest.raises(ConfigError):
            await module.create_instrument({"id": "bad", "transport": "visa",
                                            "params": {"resource": "q"}, "stations": ["st9"]})
    finally:
        await db.close()


async def test_python_owned_instrument_crud(ctx):
    module, _, _ = ctx
    inst = await module.create_instrument({
        "id": "psu9", "owner": "python", "library": "ctest_supply", "simulated": True,
        "params": {"resource": "TCPIP0::1.2.3.4::inst0::INSTR"},
    })
    assert inst["owner"] == "python" and inst["library"] == "ctest_supply"
    assert inst["address"] == "TCPIP0::1.2.3.4::inst0::INSTR"   # from params.resource
    py = await module.python_instruments()
    assert py == [{"id": "psu9", "library": "ctest_supply",
                   "params": {"resource": "TCPIP0::1.2.3.4::inst0::INSTR"}, "simulated": True,
                   "stations": ["st1"]}]


async def test_python_owned_validation(ctx):
    module, _, _ = ctx
    with pytest.raises(ConfigError):
        await module.create_instrument({"id": "a", "owner": "python", "library": "nope", "params": {"resource": "r"}})
    with pytest.raises(ConfigError):   # resource is required (no default)
        await module.create_instrument({"id": "b", "owner": "python", "library": "ctest_supply", "params": {}})


async def test_labview_owned_excluded_from_python_feed(ctx):
    module, _, _ = ctx
    await module.create_instrument({"id": "dmm0", "transport": "modbus_tcp",
                                    "params": {"host": "10.0.0.5", "port": 502, "unit_id": 1}})
    assert await module.python_instruments() == []   # owner defaults to labview


async def test_crud_and_address_render(ctx):
    module, _, _ = ctx
    inst = await module.create_instrument({
        "id": "dmm0", "label": "Digital Multimeter", "transport": "modbus_tcp",
        "params": {"host": "192.168.0.20", "port": 502, "unit_id": 3}, "family": "dmm",
    })
    assert inst["address"] == "192.168.0.20:502 (unit 3)"
    assert [i["id"] for i in await module.list_instruments()] == ["dmm0"]
    up = await module.update_instrument("dmm0", {"transport": "modbus_tcp",
         "params": {"host": "10.0.0.5", "port": 502, "unit_id": 1}, "label": "DMM"})
    assert up["address"].startswith("10.0.0.5")
    assert await module.delete_instrument("dmm0") is True
    assert await module.list_instruments() == []


async def test_validation(ctx):
    module, _, _ = ctx
    with pytest.raises(ConfigError):
        await module.create_instrument({"id": "Bad ID", "transport": "visa", "params": {"resource": "x"}})
    with pytest.raises(ConfigError):
        await module.create_instrument({"id": "x1", "transport": "nope", "params": {}})
    with pytest.raises(ConfigError):  # missing required field
        await module.create_instrument({"id": "x1", "transport": "visa", "params": {}})


async def test_test_connection_online(ctx):
    module, _, _ = ctx
    out = await module.test_connection({"transport": "visa", "params": {"resource": "TCPIP0::1.2.3.4::INSTR"}})
    assert out["ok"] is True and out["status"] == "pass"
    assert out["identity"] == "ACME,DMM-1,1.0"


async def test_test_connection_offline_is_unavailable():
    module, _, db = await _build(FakeBridge(online=False))
    try:
        out = await module.test_connection({"transport": "visa", "params": {"resource": "x"}})
        assert out["ok"] is False and out["status"] == "unavailable"
    finally:
        await db.close()

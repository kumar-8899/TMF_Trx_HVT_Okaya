"""config standalone tester (CORE.md §6.2) — core + config, :memory: db."""

import pytest

from core.framework.contract import CoreServices
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.config.variants.default import ConfigError, DefaultConfig


class FakeBridge:
    def __init__(self, online=True, reply=None):
        self._online = online
        self.reply = reply or {"ok": True, "identity": "ACME,DMM-1,1.0", "detail": "connected"}
        self.requests = []

    @property
    def online(self):
        return self._online

    async def request(self, op, args, timeout=None):
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

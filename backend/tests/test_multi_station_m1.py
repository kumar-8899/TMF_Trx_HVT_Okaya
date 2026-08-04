"""M1 — app.json stations list, singular-key migration, license max_stations cap,
CoreServices.stations (MULTI_STATION.md §1, §9 slice M1)."""

import json
import shutil

import httpx
from httpx import ASGITransport

from core.app import create_app
from core.services.config import DEFAULT_CONFIG_DIR, ConfigService
from core.services.licensing import License


# ---- config migration (unit) ---------------------------------------------

def _write_app(config_dir, app):
    (config_dir / "app.json").write_text(json.dumps(app), encoding="utf-8")


def _base_app(**over):
    app = {"schema_version": 1, "license": "config/license.json",
           "modules": [{"id": "hello", "variant": "default"}]}
    app.update(over)
    return app


def test_singular_station_migrates_to_list(config_dir):
    _write_app(config_dir, _base_app(station="st1"))
    cfg = ConfigService(config_dir).load_app()
    assert cfg["stations"] == ["st1"]
    assert cfg["station"] == "st1"            # back-compat alias
    assert cfg["stations_migrated"] is True


def test_stations_list_is_kept(config_dir):
    _write_app(config_dir, _base_app(stations=["st1", "st2", "st3"]))
    cfg = ConfigService(config_dir).load_app()
    assert cfg["stations"] == ["st1", "st2", "st3"]
    assert cfg["station"] == "st1"            # alias = first socket
    assert not cfg.get("stations_migrated")


# ---- license cap (unit) ---------------------------------------------------

def test_license_max_stations_read():
    lic = License({"entitlements": {"limits": {"max_stations": 2}}}, valid=True)
    assert lic.max_stations() == 2


def test_license_max_stations_absent_is_none():
    assert License({"entitlements": {}}, valid=True).max_stations() is None
    assert License({}, valid=False).max_stations() is None   # invalid -> no entitlements


# ---- end to end: cap applied, refusals surfaced --------------------------

def _seed(config_dir, *, stations, max_stations):
    lic = json.loads((DEFAULT_CONFIG_DIR / "license.example.json").read_text())
    lic["entitlements"]["limits"]["max_stations"] = max_stations
    # licence-gate the hello module on so the app boots something
    lic["entitlements"]["modules"] = {"hello": True}
    (config_dir / "license.json").write_text(json.dumps(lic), encoding="utf-8")
    _write_app(config_dir, _base_app(stations=stations))


async def test_modules_status_caps_stations(config_dir):
    _seed(config_dir, stations=["st1", "st2", "st3", "st4"], max_stations=2)
    app = create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            body = (await c.get("/modules/status")).json()
            assert body["stations"] == ["st1", "st2"]
            assert body["station_refusals"] == ["st3", "st4"]


async def test_all_stations_when_under_cap(config_dir):
    _seed(config_dir, stations=["st1", "st2"], max_stations=4)
    app = create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            body = (await c.get("/modules/status")).json()
            assert body["stations"] == ["st1", "st2"]
            assert body["station_refusals"] == []

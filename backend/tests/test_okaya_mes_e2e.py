"""okaya_mes through the FULL app: the shipped example config + license activate it (autodiscovery, manifest,
schema, entitlement), its REST is mounted and permission-gated, and a configured sqlite table is created."""

import httpx
from httpx import ASGITransport

from core.app import create_app


def _app(config_dir):
    return create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)


async def _admin(c):
    r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_okaya_mes_is_loaded_licensed_and_serves_its_rest(config_dir, tmp_path):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            mods = {m["id"]: m for m in (await c.get("/modules/status")).json()["modules"]}
            assert mods["okaya_mes"]["status"] == "loaded", mods["okaya_mes"]
            assert (await c.get("/okaya-mes/status")).status_code == 401            # gated
            admin = await _admin(c)
            st = (await c.get("/okaya-mes/status", headers=admin)).json()
            assert st["enabled"] is False and st["ready"] is False                  # off + unconfigured by default

            cfg = {"enabled": True, "station_name": "HV Testing", "table": "txr_testtable",
                   "connection": {"provider": "sqlite", "path": str(tmp_path / "okaya.sqlite")}}
            assert (await c.put("/okaya-mes/config", json=cfg, headers=admin)).status_code == 200
            made = (await c.post("/okaya-mes/table/create", json={}, headers=admin)).json()
            assert made["ok"] is True and made["missing"] == []
            st = (await c.get("/okaya-mes/status", headers=admin)).json()
            assert st["enabled"] is True and st["ready"] is True and st["table"] == "txr_testtable"


async def test_okaya_mes_is_skipped_not_fatal_when_the_license_lacks_it(config_dir):
    import json
    lic = json.loads((config_dir / "license.example.json").read_text(encoding="utf-8"))
    lic["entitlements"]["modules"].pop("okaya_mes")
    (config_dir / "license.example.json").write_text(json.dumps(lic), encoding="utf-8")
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            mods = {m["id"]: m for m in (await c.get("/modules/status")).json()["modules"]}
            assert mods["okaya_mes"]["status"] == "skipped" and "licensed" in mods["okaya_mes"]["reason"]
            assert (await c.get("/healthz")).status_code == 200                      # the app still comes up

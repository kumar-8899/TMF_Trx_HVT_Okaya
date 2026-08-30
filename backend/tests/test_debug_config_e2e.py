"""Remote-debugging on/off + the live diag-level relay, through the full app.

/system/debug-config toggles the flight-recorder sidecar in app.json (applied on
relaunch by station.py); /diag/level sets live per-subsystem verbosity. Both are
SYSTEM.SETTINGS-gated.
"""

import httpx
from httpx import ASGITransport

from core.app import create_app


def _app(config_dir):
    return create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)


async def _admin(c):
    r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_debug_config_get_defaults(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            d = (await c.get("/system/debug-config", headers=await _admin(c))).json()
            assert d["enabled"] is False and d["bind_host"] == "127.0.0.1"
            assert d["running"] is False and d["has_token"] is False


async def test_debug_config_enable_persists(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.put("/system/debug-config", headers=admin, json={"enabled": True})
            assert r.status_code == 200 and r.json()["enabled"] is True
            assert r.json()["restart_required"] is True
            d = (await c.get("/system/debug-config", headers=admin)).json()
            assert d["enabled"] is True


async def test_debug_config_rejects_unsafe_bind(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            assert (await c.put("/system/debug-config", headers=admin,
                                json={"bind_host": "0.0.0.0"})).status_code == 422
            # remote bind without a token is refused
            assert (await c.put("/system/debug-config", headers=admin,
                                json={"enabled": True, "bind_host": "192.168.1.5"})).status_code == 422
            # remote bind WITH a token is accepted
            assert (await c.put("/system/debug-config", headers=admin,
                                json={"bind_host": "192.168.1.5", "token": "s3cret"})).status_code == 200


async def test_debug_config_requires_permission(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.put("/system/debug-config", json={"enabled": True})).status_code == 401


async def test_diag_level_get_and_set(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            d = (await c.get("/diag/level", headers=admin)).json()
            assert d["default"] == "debug" and d["overrides"] == {}
            r = await c.put("/diag/level", headers=admin, json={"subsystem": "daq", "level": "warning"})
            assert r.status_code == 200 and r.json()["overrides"] == {"daq": "warning"}
            assert (await c.put("/diag/level", headers=admin,
                                json={"subsystem": "daq", "level": "verbose"})).status_code == 422
            assert (await c.put("/diag/level", json={"subsystem": "daq", "level": "info"})).status_code == 401

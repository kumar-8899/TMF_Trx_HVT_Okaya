"""Station configuration endpoints (Settings → Station) through the full app.

/system/station-config edits boot config (socket count st1..stN + controller kind) in
app.json; it is SYSTEM.SETTINGS-gated and takes effect on restart. Socket count is capped
at the licensed max_stations. /system/relaunch is not exercised here (it exits the process).
"""

import httpx
from httpx import ASGITransport

from core.app import create_app


def _app(config_dir):
    return create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)


async def _admin(c):
    r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_get_reports_count_controller_and_cap(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            d = (await c.get("/system/station-config", headers=admin)).json()
            assert d["station_count"] >= 1
            assert d["controller"]["kind"] in ("labview", "python")
            assert "max_stations" in d and "restart_required" in d


async def test_put_sets_controller_and_persists(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.put("/system/station-config", headers=admin,
                            json={"station_count": 1, "controller_kind": "python"})
            assert r.status_code == 200
            body = r.json()
            assert body["configured_stations"] == ["st1"]
            assert body["controller"]["kind"] == "python"
            # simulation is per-instrument (Instruments page) — no app-level knob
            assert "simulation" not in body["controller"]
            assert body["restart_required"] is True           # controller kind changed vs running
            # a fresh GET reflects the written app.json
            d = (await c.get("/system/station-config", headers=admin)).json()
            assert d["controller"]["kind"] == "python"


async def test_put_enforces_license_cap(config_dir):
    """The example license caps max_stations=1, so more sockets is refused (fail-closed)."""
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            d = (await c.get("/system/station-config", headers=admin)).json()
            over = (d["max_stations"] or 1) + 1
            r = await c.put("/system/station-config", headers=admin, json={"station_count": over})
            assert r.status_code == 422 and "max_stations" in str(r.json())


async def test_put_rejects_bad_input(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            assert (await c.put("/system/station-config", headers=admin,
                                json={"station_count": 0})).status_code == 422
            assert (await c.put("/system/station-config", headers=admin,
                                json={"controller_kind": "matlab"})).status_code == 422
            assert (await c.put("/system/station-config", headers=admin,
                                json={})).status_code == 422


async def test_put_requires_permission(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.put("/system/station-config", json={"station_count": 2})).status_code == 401


async def test_shutdown_requires_permission(config_dir):
    """Only the no-auth path is exercised — a permitted call raises SIGINT and would exit
    the test process. 401 confirms the safe-exit endpoint exists and is gated."""
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.post("/system/shutdown", json={})).status_code == 401
            assert (await c.post("/system/relaunch", json={})).status_code == 401

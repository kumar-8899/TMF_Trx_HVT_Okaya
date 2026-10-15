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


async def test_relaunch_stops_the_controller_before_exiting(config_dir, monkeypatch):
    """os._exit(42) skips the lifespan teardown, so the relaunch endpoints must stop the
    supervised Python controller themselves — otherwise `run.exe --controller` is orphaned,
    keeps run.dist open (blocking every swap) and stays a second process driving instruments."""
    import core.app as core_app

    events: list[str] = []
    monkeypatch.setattr(core_app.os, "_exit", lambda code: events.append(f"exit{code}"))

    class _ImmediateTimer:
        def __init__(self, _delay, fn):
            self._fn = fn

        def start(self):
            self._fn()

    monkeypatch.setattr(core_app.threading, "Timer", _ImmediateTimer)

    class _FakeController:
        def stop(self):
            events.append("stop")
            return True

    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        app.state.controller = _FakeController()
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.post("/system/relaunch", json={}, headers=admin)
            assert r.status_code == 200
    # the controller is stopped BEFORE the process exit is scheduled (the trailing "stop" is
    # the lifespan teardown, which os._exit(42) would skip in a real relaunch).
    assert events[:2] == ["stop", "exit42"]


async def test_exit_station_is_open_to_any_role_holding_system_exit(config_dir, monkeypatch):
    """X5: an operator (SYSTEM.EXIT, no SYSTEM.SETTINGS) can exit the station; a role stripped of
    SYSTEM.EXIT cannot; relaunch stays SYSTEM.SETTINGS-only. The real shutdown raises SIGINT, so the
    signal + hard-exit watchdog are stubbed."""
    import core.app as core_app
    raised: list[str] = []
    monkeypatch.setattr(core_app.signal, "raise_signal", lambda s: raised.append("sigint"))

    class _NoTimer:
        daemon = False

        def __init__(self, *a, **k): pass
        def start(self): pass
    monkeypatch.setattr(core_app.threading, "Timer", _NoTimer)

    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            made = (await c.post("/auth/users", headers=admin, json={"username": "ollie", "role": "operator"})).json()
            r = await c.post("/auth/login", json={"username": "ollie", "credential": {"password": made["temp_password"]}})
            op = {"Authorization": f"Bearer {r.json()['token']}"}
            assert "SYSTEM.EXIT" in r.json()["principal"]["permissions"]
            assert "SYSTEM.SETTINGS" not in r.json()["principal"]["permissions"]
            assert (await c.post("/system/shutdown", headers=op, json={})).status_code == 200
            assert (await c.post("/system/relaunch", headers=op, json={})).status_code == 403   # still settings-only

            # take SYSTEM.EXIT away from operator -> exit is refused for a fresh login
            assert (await c.put("/auth/roles/operator", headers=admin,
                                json={"permissions": ["TEST.RUN"]})).status_code == 200
            r2 = await c.post("/auth/login", json={"username": "ollie", "credential": {"password": made["temp_password"]}})
            op2 = {"Authorization": f"Bearer {r2.json()['token']}"}
            assert (await c.post("/system/shutdown", headers=op2, json={})).status_code == 403


async def test_odbc_drivers_endpoint_lists_installed_drivers_for_any_signed_in_role(config_dir, monkeypatch):
    from core.services import dbconn
    monkeypatch.setattr(dbconn, "odbc_drivers", lambda: ["ODBC Driver 18 for SQL Server", "SQL Server"])
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/system/odbc-drivers")).status_code == 401          # signed-in only
            r = await c.get("/system/odbc-drivers", headers=await _admin(c))
            assert r.json() == {"drivers": ["ODBC Driver 18 for SQL Server", "SQL Server"],
                                "default": "ODBC Driver 18 for SQL Server"}
            monkeypatch.setattr(dbconn, "odbc_drivers", lambda: [])
            assert (await c.get("/system/odbc-drivers", headers=await _admin(c))).json() == {"drivers": [], "default": None}

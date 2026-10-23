"""D11 / X8 - an operator whose role was stripped of CONFIG.VIEW must still be able to run a test.

Field failure: the Test Bench's Start dialog read `/config/barcode` and `/config/shift/current`
(both CONFIG.VIEW), the Runs screen swallowed the 403, and the serial-number box silently
disappeared. Instrument connection status (`/variables/instances`) was CONFIG.VIEW too, so the
Dashboard showed nothing. Now:
  - barcode layout + current shift: TEST.RUN or CONFIG.VIEW (any-of),
  - instrument STATUS: any signed-in role (status only - no connection params),
  - every config write / list / instrument config stays CONFIG.VIEW / CONFIG.EDIT."""

import httpx
from httpx import ASGITransport

from core.app import create_app


def _app(config_dir):
    return create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)


async def _admin(c):
    r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _login_as(c, admin, name, role):
    made = (await c.post("/auth/users", headers=admin, json={"username": name, "role": role})).json()
    r = await c.post("/auth/login", json={"username": name, "credential": {"password": made["temp_password"]}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_test_run_only_role_can_load_the_start_dialog_but_not_configure(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            # operator keeps TEST.RUN but loses CONFIG.VIEW (what an admin can do in the role matrix)
            assert (await c.put("/auth/roles/operator", headers=admin,
                                json={"permissions": ["TEST.RUN", "RECIPE.VIEW"]})).status_code == 200
            op = await _login_as(c, admin, "olga", "operator")

            assert (await c.get("/config/barcode", headers=op)).status_code == 200
            assert (await c.get("/config/shift/current", headers=op)).status_code == 200
            assert (await c.get("/variables/instances", headers=op)).status_code == 200      # X8: status

            # ...and nothing else under /config or /variables opened up
            for url in ("/config/shift", "/config/instruments", "/config/transports",
                        "/variables", "/variables/bindings", "/variables/libraries"):
                assert (await c.get(url, headers=op)).status_code == 403, url
            for method, url, body in (("put", "/config/barcode", {}), ("put", "/config/shift", {}),
                                      ("post", "/config/instruments", {})):
                assert (await getattr(c, method)(url, headers=op, json=body)).status_code == 403, url


async def test_a_role_with_neither_test_run_nor_config_view_is_still_refused(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            assert (await c.put("/auth/roles/operator", headers=admin,
                                json={"permissions": ["REPORT.VIEW"]})).status_code == 200
            op = await _login_as(c, admin, "ruth", "operator")
            assert (await c.get("/config/barcode", headers=op)).status_code == 403
            assert (await c.get("/config/shift/current", headers=op)).status_code == 403
            assert (await c.get("/variables/instances", headers=op)).status_code == 200   # status: any role
            assert (await c.get("/config/barcode")).status_code == 401                      # no token
            assert (await c.get("/variables/instances")).status_code == 401


async def test_instrument_status_carries_no_connection_params(config_dir):
    """Opening status to every role is only safe because it is status only."""
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            op = await _login_as(c, admin, "olga", "operator")
            for row in (await c.get("/variables/instances", headers=op)).json():
                assert set(row) <= {"id", "library", "capabilities", "state", "simulated", "reason"}

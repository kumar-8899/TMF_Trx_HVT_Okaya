"""Branding override endpoint (Setup wizard / App identity) through the full app.

/branding is public and merges defaults ∪ app.json ∪ the DB override; PUT persists the
override and is super_admin-gated. A station rebrands live, without editing app.json.
"""

import httpx
from httpx import ASGITransport

from core.app import create_app


def _app(config_dir):
    return create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)


async def _admin(c):
    r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_branding_get_is_public_and_has_defaults(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            b = (await c.get("/branding")).json()
            assert b["name"] and b["product"] and b["version"]


async def test_put_persists_and_get_reflects(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.put("/branding", headers=admin, json={
                "name": "Acme EOL", "short": "AE", "product": "Acme EOL Tester", "tagline": "Line 3"})
            assert r.status_code == 200 and r.json()["name"] == "Acme EOL"
            # public GET now returns the override (live, no restart)
            b = (await c.get("/branding")).json()
            assert b == r.json()
            assert b["short"] == "AE" and b["product"] == "Acme EOL Tester"


async def test_put_requires_super_admin(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.put("/branding", json={"name": "x"})).status_code == 401


async def test_put_rejects_empty_name(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            assert (await c.put("/branding", headers=admin, json={"name": "  "})).status_code == 400

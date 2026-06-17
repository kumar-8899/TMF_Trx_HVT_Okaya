"""Auth end-to-end through the full app (no broker). CORE.md §4/§6.4 + the MD."""

import json
import shutil

import httpx
from httpx import ASGITransport

from core.app import create_app
from core.services.config import DEFAULT_CONFIG_DIR


def _app(config_dir):
    return create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)


async def test_auth_active_login_me_and_gate(config_dir):
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert "auth" in (await c.get("/modules/status")).json()["loaded"]

            # login the seeded admin (dev admin/admin)
            r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
            assert r.status_code == 200
            token = r.json()["token"]
            assert "AUTH.*" in r.json()["principal"]["permissions"]
            admin = {"Authorization": f"Bearer {token}"}

            me = await c.get("/auth/me", headers=admin)
            assert me.status_code == 200 and me.json()["role"] == "super_admin"

            # AUTH.MANAGE_USERS gate: no token 401, admin 200, operator 403
            assert (await c.get("/auth/users")).status_code == 401
            assert (await c.get("/auth/users", headers=admin)).status_code == 200

            # create issues a temp password; the new user logs in with it
            created = await c.post("/auth/users", headers=admin,
                                   json={"username": "op", "role": "operator"})
            assert created.status_code == 201
            temp = created.json()["temp_password"]
            op_login = await c.post("/auth/login", json={"username": "op", "credential": {"password": temp}})
            assert op_login.json()["principal"]["must_change_password"] is True
            op = {"Authorization": f"Bearer {op_login.json()['token']}"}
            assert (await c.get("/auth/users", headers=op)).status_code == 403

            # single active session: re-login admin revokes the first token
            r2 = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
            assert r2.status_code == 200
            assert (await c.get("/auth/me", headers=admin)).status_code == 401


async def test_license_flip_disables_auth(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    shutil.copyfile(DEFAULT_CONFIG_DIR / "app.example.json", cfg / "app.example.json")
    lic = json.loads((DEFAULT_CONFIG_DIR / "license.example.json").read_text())
    lic["entitlements"]["modules"]["auth"] = False
    (cfg / "license.example.json").write_text(json.dumps(lic))

    app = _app(cfg)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            status = (await c.get("/modules/status")).json()
            assert "auth" not in status["loaded"]
            assert {s["id"]: s["reason"] for s in status["skipped"]}["auth"] == "not licensed"
            # no Auth module -> no /auth routes, core.auth stays fail-closed
            assert (await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})).status_code == 404

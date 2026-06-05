"""Logs end-to-end through the full app (no broker). LOGS.md §10, prompt §8."""

import asyncio
import json
import shutil

import httpx
from httpx import ASGITransport

from core.app import create_app
from core.services.config import DEFAULT_CONFIG_DIR


async def _until(fn, timeout=5.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if await fn():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_logs_loaded_and_diag_persists(config_dir):
    app = create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert "logs" in (await c.get("/modules/status")).json()["loaded"]

            # a diag from anywhere persists as error_log with no call-site change
            app.state.diag.warning("daq", "persisted-warning", code=7)

            async def has_row():
                rows = await app.state.db.repo.query("error_log")
                return any(r["data"]["message"] == "persisted-warning" for r in rows)

            assert await _until(has_row)

            # readable over REST with a DIAGNOSTICS.VIEW principal (admin/super_admin)
            login = await c.post("/auth/login",
                                 json={"username": "admin", "credential": {"password": "admin"}})
            bearer = {"Authorization": f"Bearer {login.json()['token']}"}
            errs = await c.get("/logs/errors", headers=bearer)
            assert errs.status_code == 200
            assert any(it["data"]["message"] == "persisted-warning" for it in errs.json()["items"])
            assert (await c.get("/logs/errors")).status_code == 401  # gated


async def test_license_flip_disables_logs(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    shutil.copyfile(DEFAULT_CONFIG_DIR / "app.example.json", cfg / "app.example.json")
    lic = json.loads((DEFAULT_CONFIG_DIR / "license.example.json").read_text())
    lic["entitlements"]["modules"]["logs"] = False
    (cfg / "license.example.json").write_text(json.dumps(lic))

    app = create_app(config_dir=cfg, db_path=":memory:", enable_bridge=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            status = (await c.get("/modules/status")).json()
            assert "logs" not in status["loaded"]
            assert {s["id"]: s["reason"] for s in status["skipped"]}["logs"] == "not licensed"
            assert (await c.get("/logs/errors")).status_code == 404  # no routes mounted

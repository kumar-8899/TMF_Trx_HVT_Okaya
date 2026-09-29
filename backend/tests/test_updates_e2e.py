"""Update endpoints through the full app — the `updates.station_mode` source gate.

`online` (default): /update/check + /update/download reachable, /update/install-file → 409.
`air_gapped`: the reverse. The gate is a SOURCE restriction, orthogonal to allow_unverified.
"""

import json

import httpx
from httpx import ASGITransport

from core.app import create_app


def _write_app_json(config_dir, **updates):
    base = json.loads((config_dir / "app.example.json").read_text(encoding="utf-8"))
    base.setdefault("updates", {})
    base["updates"].update({"github_repo": "owner/repo", **updates})
    (config_dir / "app.json").write_text(json.dumps(base), encoding="utf-8")


def _app(config_dir):
    return create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)


async def _admin(c):
    r = await c.post("/auth/login", json={"username": "admin", "credential": {"password": "admin"}})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_offers_reports_station_mode_default_online(config_dir):
    _write_app_json(config_dir)                       # no station_mode set
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.get("/update/offers", headers=admin)
            assert r.status_code == 200 and r.json()["station_mode"] == "online"


async def test_air_gapped_blocks_check_and_download_with_409(config_dir):
    _write_app_json(config_dir, station_mode="air_gapped")
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            assert (await c.get("/update/offers", headers=admin)).json()["station_mode"] == "air_gapped"
            for path in ("/update/check", "/update/download"):
                r = await c.post(path, json={}, headers=admin)
                assert r.status_code == 409, path
                assert "air-gapped" in str(r.json()), (path, r.json())


async def test_online_blocks_install_file_with_409(config_dir):
    _write_app_json(config_dir, station_mode="online")
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.post("/update/install-file",
                             json={"ksupdate_path": "x.ksupdate", "zip_path": "x.zip"}, headers=admin)
            assert r.status_code == 409, r.json()
            assert "online" in str(r.json()), r.json()


# --- /update/scan-incoming: same source gate as install-file --------------------------------

async def test_online_blocks_scan_incoming_with_409(config_dir):
    _write_app_json(config_dir, station_mode="online")
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.post("/update/scan-incoming", headers=admin)
            assert r.status_code == 409, r.json()
            assert "online" in str(r.json()), r.json()


async def test_air_gapped_scan_incoming_finds_nothing_when_no_files_staged(config_dir):
    _write_app_json(config_dir, station_mode="air_gapped")
    app = _app(config_dir)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            admin = await _admin(c)
            r = await c.post("/update/scan-incoming", headers=admin)
            assert r.status_code == 200 and r.json()["found"] == []

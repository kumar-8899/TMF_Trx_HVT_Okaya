"""hello standalone tester (CORE.md §6.2, §9).

Standalone = core + this module + a stub for the bridge. Runs anywhere — no
broker. Proves the route, the diagnostic, gate activation, and the license flip.
The real MQTT round-trip is covered by tests/test_hello_e2e.py.
"""

import httpx
from fastapi import FastAPI
from httpx import ASGITransport

import modules.hello  # noqa: F401 — import registers the module
from core.framework.contract import Core
from core.framework.gate import activate_modules
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.config import ConfigService
from core.services.diagnostics import Diagnostics
from core.services.licensing import License
from core.services.web import install_web


class StubBridge:
    station = "st1"
    online = True

    async def request(self, op: str, args: dict, timeout=None) -> dict:
        assert op == "hello.echo"
        return {"id": "stub", "ok": True, "result": {"echoed": args, "station": "st1", "ts": 0.0}}

    async def publish(self, *a, **k):
        pass

    def subscribe(self, *a, **k):
        pass


class StubDB:
    async def run_migrations(self, _):
        return []


def _license(hello_on: bool) -> License:
    return License(
        {"entitlements": {"modules": {"hello": hello_on}, "variants": {"hello": ["default"]}}},
        valid=True,
    )


async def _build_app(tmp_path, *, hello_on=True):
    diag_events: list = []
    app = FastAPI()
    web = install_web(app)
    core = Core(
        db=StubDB(),
        bridge=StubBridge(),
        config=ConfigService(tmp_path),
        diag=Diagnostics("st1", "0.0.0", sinks=[diag_events.append]),
        web=web,
        station="st1",
    )
    result = await activate_modules(
        core=core,
        registry=default_registry,
        manifests=ManifestLoader(),  # real backend/modules dir
        app_config={"modules": [{"id": "hello", "variant": "default"}]},
        license=_license(hello_on),
        diag=core.diag,
    )
    return app, result, diag_events


def _client(app):
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_ping_round_trips_and_emits_diag(tmp_path):
    app, result, diag_events = await _build_app(tmp_path)
    assert "hello" in result.active

    async with _client(app) as client:
        resp = await client.get("/hello/ping")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pong"] is True
    assert body["station"] == "st1"
    assert body["echo"]["ok"] is True
    assert body["echo"]["result"]["echoed"]["from"] == "hello"

    pinged = [e for e in diag_events if e["message"] == "pinged"]
    assert len(pinged) == 1 and pinged[0]["subsystem"] == "hello"


async def test_license_flip_unloads_hello(tmp_path):
    # CORE.md §10 #3 — hello=false makes it not load, with the reason recorded.
    app, result, _ = await _build_app(tmp_path, hello_on=False)
    assert "hello" not in result.active
    skipped = {s["id"]: s["reason"] for s in result.status_payload()["skipped"]}
    assert skipped["hello"] == "not licensed"

    async with _client(app) as client:
        resp = await client.get("/hello/ping")
    assert resp.status_code == 404


async def test_health_reflects_bridge(tmp_path):
    app, result, _ = await _build_app(tmp_path)
    health = await result.active["hello"].health()
    assert health.status.value == "ok"

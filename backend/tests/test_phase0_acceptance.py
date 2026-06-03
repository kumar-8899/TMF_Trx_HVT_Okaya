"""Phase-0 acceptance — the walking-skeleton "done" gate (CORE.md §10).

One consolidated walk of the §10 criteria against the full app + the reference
LabVIEW stub. This test IS the definition of done. The broker-backed walk is
skipped without mosquitto (it runs in CI); the license-flip and sidecar checks
run anywhere.
"""

import asyncio
import json
import shutil

import httpx
import pytest
from httpx import ASGITransport

from core.app import create_app
from core.services.config import DEFAULT_CONFIG_DIR
from tests._mqtt import Broker, find_mosquitto
from tools.lv_stub import LabviewStub


async def _until(client, path, want, timeout=8.0):
    end = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < end:
        last = await client.get(path)
        if last.status_code == want:
            return last
        await asyncio.sleep(0.1)
    return last


# --- the full broker-backed walk: criteria #1, #2, #4, #5, #6, #7 ----------

requires_broker = pytest.mark.skipif(find_mosquitto() is None, reason="mosquitto not installed")


@pytest.fixture
async def broker(tmp_path):
    b = Broker(tmp_path)
    b.start()
    yield b
    b.stop()


@requires_broker
async def test_phase0_end_to_end(broker, config_dir):
    stub = LabviewStub(broker.host, broker.port, station="st1",
                       stream_hz=20.0, value_period=0.2, status_period=0.5)
    await stub.start()
    app = create_app(
        config_dir=config_dir, db_path=":memory:",
        enable_bridge=True, broker_host=broker.host, broker_port=broker.port,
    )
    frames = {"stream": [], "value": [], "diag": []}
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                # #1 — app booted through the lifecycle; core services up.
                assert (await c.get("/healthz")).json()["status"] == "ok"

                # #2 — hello activated through the gate.
                status = (await c.get("/modules/status")).json()
                assert "hello" in status["loaded"]

                # #4 — /readyz green only once the bridge link is online.
                ready = await _until(c, "/readyz", 200)
                assert ready.status_code == 200
                assert ready.json()["checks"] == {"bridge": True, "db": True}

                # #6 — one stream frame + retained value + diag flow LV->Py.
                bridge = app.state.bridge
                bridge.subscribe("stream/ai", lambda t, p: frames["stream"].append(p))
                bridge.subscribe("value/vbus_main", lambda t, p: frames["value"].append(p))
                bridge.subscribe("diag", lambda t, p: frames["diag"].append(p))
                for kind in ("stream", "value", "diag"):
                    await _until_list(frames[kind], kind)
                assert "ai0" in frames["stream"][0]["values"]
                assert isinstance(frames["value"][0]["value"], (int, float))

                # #5 — /hello/ping round-trips through MQTT to the stub.
                ping = (await c.get("/hello/ping")).json()
                assert ping["pong"] is True and ping["echo"]["ok"] is True
                assert ping["echo"]["result"]["echoed"]["from"] == "hello"

                # #7 — kill the stub link -> status offline -> /readyz not-ready.
                await stub.stop()
                notready = await _until(c, "/readyz", 503)
                assert notready.status_code == 503
                assert notready.json()["checks"]["bridge"] is False
    finally:
        await stub.stop()


async def _until_list(lst, what, timeout=8.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if lst:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


# --- criterion #3: license flip (no broker needed) -------------------------


async def test_criterion3_license_flip(tmp_path):
    """Flipping hello to false in license.json makes it not load, reason shown."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    shutil.copyfile(DEFAULT_CONFIG_DIR / "app.example.json", cfg_dir / "app.example.json")
    lic = json.loads((DEFAULT_CONFIG_DIR / "license.example.json").read_text())
    lic["entitlements"]["modules"]["hello"] = False
    (cfg_dir / "license.example.json").write_text(json.dumps(lic))

    app = create_app(config_dir=cfg_dir, db_path=":memory:", enable_bridge=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            status = (await c.get("/modules/status")).json()
            assert "hello" not in status["loaded"]
            reasons = {s["id"]: s["reason"] for s in status["skipped"]}
            assert reasons["hello"] == "not licensed"
            assert (await c.get("/hello/ping")).status_code == 404


# --- criterion #8: the build entrypoints exist (CI does the actual builds) --


def test_criterion8_sidecar_entrypoint():
    """CI builds the PyInstaller sidecar; here we assert its entrypoint is sound."""
    import run

    assert callable(run.main)
    assert callable(create_app)

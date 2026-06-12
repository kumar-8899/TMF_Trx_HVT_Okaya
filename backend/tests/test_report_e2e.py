"""Report end-to-end: fake LV emits event/run-* -> report persisted -> REST.

Full app over a real broker. Skipped without mosquitto.
"""

import asyncio

import httpx
import pytest
from httpx import ASGITransport

from core.app import create_app
from core.services.bridge import BridgeClient
from tests._mqtt import Broker, find_mosquitto

pytestmark = pytest.mark.skipif(find_mosquitto() is None, reason="mosquitto not installed")


@pytest.fixture
async def broker(tmp_path):
    b = Broker(tmp_path)
    b.start()
    yield b
    b.stop()


async def _until(c, path, want, headers, timeout=6.0):
    end = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < end:
        last = await c.get(path, headers=headers)
        if last.status_code == want:
            return last
        await asyncio.sleep(0.1)
    return last


async def test_run_events_produce_a_report(broker, config_dir):
    lv = BridgeClient("st1", host=broker.host, port=broker.port, client_id="lv")
    app = create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=True,
                     broker_host=broker.host, broker_port=broker.port)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            login = await c.post("/auth/login",
                                 json={"username": "admin", "credential": {"password": "admin"}})
            hdr = {"Authorization": f"Bearer {login.json()['token']}"}

            await lv.connect(wait_timeout=5)
            await asyncio.sleep(0.3)  # subscriptions land

            async def emit(etype, payload, ts):
                await lv.publish("event/" + etype, {"type": etype, "ts": ts, "payload": payload})
                await asyncio.sleep(0.1)  # let runs persist before the next event

            await emit("run-started", {"run_id": "E1", "recipe": "inv-c", "version": 1}, 1.0)
            await emit("step-completed",
                       {"run_id": "E1", "step_id": "s1", "status": "PASSED",
                        "measurements": [{"name": "vbus", "value": 264.0}]}, 2.0)
            await emit("run-finished", {"run_id": "E1", "result": "PASS"}, 3.0)

            rep = await _until(c, "/reports/E1", 200, hdr)
            assert rep.status_code == 200
            body = rep.json()
            assert body["result"] == "PASS" and body["recipe_id"] == "inv-c"
            assert body["measurements"][0]["value"] == 264.0

            an = await c.get("/reports/analytics", headers=hdr)
            assert an.json()["passed"] == 1 and an.json()["yield"] == 100.0
    await lv.disconnect()

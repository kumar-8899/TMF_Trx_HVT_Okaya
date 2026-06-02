"""hello end-to-end over real MQTT (CORE.md §10 #3, #4, #5, #7).

Boots the whole app (create_app) against a real Mosquitto with a fake-LabVIEW
responder. This is the Python-side stand-in for the LabVIEW stub; P7 repeats it
against the real stub. Skipped when mosquitto is absent.
"""

import httpx
import pytest
from httpx import ASGITransport

from core.app import create_app
from tests._mqtt import Broker, FakeLabview, find_mosquitto

pytestmark = pytest.mark.skipif(find_mosquitto() is None, reason="mosquitto not installed")


@pytest.fixture
async def broker(tmp_path):
    b = Broker(tmp_path)
    b.start()
    yield b
    b.stop()


async def _until(client, path, want_status, timeout=5.0):
    import asyncio

    end = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < end:
        last = await client.get(path)
        if last.status_code == want_status:
            return last
        await asyncio.sleep(0.1)
    return last


async def test_hello_round_trip_and_readyz(broker, config_dir):
    lv = FakeLabview(broker.host, broker.port)
    await lv.start()
    app = create_app(
        config_dir=config_dir,
        db_path=":memory:",
        enable_bridge=True,
        broker_host=broker.host,
        broker_port=broker.port,
    )
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                # #2: hello loaded through the gate
                status = (await client.get("/modules/status")).json()
                assert "hello" in status["loaded"]

                # #4: ready only once the bridge link is online
                ready = await _until(client, "/readyz", 200)
                assert ready.status_code == 200
                assert ready.json()["checks"]["bridge"] is True

                # #5: /hello/ping round-trips through MQTT to the (fake) LV stub
                ping = await client.get("/hello/ping")
                assert ping.status_code == 200
                body = ping.json()
                assert body["pong"] is True
                assert body["echo"]["ok"] is True
                assert body["echo"]["result"]["echoed"]["from"] == "hello"

                # #7: link goes offline -> /readyz goes not-ready
                await lv.set_status("offline")
                notready = await _until(client, "/readyz", 503)
                assert notready.status_code == 503
                assert notready.json()["checks"]["bridge"] is False
    finally:
        await lv.stop()

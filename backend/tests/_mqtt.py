"""Test helpers: a real Mosquitto broker + a fake LabVIEW responder.

Used by the bridge integration tests. Skipped when no mosquitto binary is on the
machine (CI installs it; local dev may not have it).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time

import aiomqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties


def find_mosquitto() -> str | None:
    found = shutil.which("mosquitto")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\mosquitto\mosquitto.exe",
        r"C:\Program Files (x86)\mosquitto\mosquitto.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(host: str, port: int, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), 0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"broker did not open {host}:{port}")


class Broker:
    def __init__(self, tmp_path) -> None:
        self.host = "127.0.0.1"
        self.port = free_port()
        self._proc: subprocess.Popen | None = None
        self._conf = tmp_path / "mosq.conf"

    def start(self) -> None:
        self._conf.write_text(
            f"listener {self.port} 127.0.0.1\nallow_anonymous true\npersistence false\n"
        )
        exe = find_mosquitto()
        assert exe, "mosquitto not found"
        self._proc = subprocess.Popen(
            [exe, "-c", str(self._conf)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_port(self.host, self.port)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


class FakeLabview:
    """Minimal LV-side responder: retained status online, replies to hello.echo."""

    def __init__(self, host: str, port: int, station: str = "st1") -> None:
        self._host, self._port, self.station = host, port, station
        self._status_topic = f"tmf/{station}/status"
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._stop = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._ready.wait(), 5)

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def publish(self, sub_topic: str, payload: dict, *, qos: int = 1, retain: bool = False) -> None:
        assert self._client is not None
        await self._client.publish(
            f"tmf/{self.station}/{sub_topic}", json.dumps(payload), qos=qos, retain=retain
        )

    async def set_status(self, state: str) -> None:
        await self.publish("status", {"state": state, "ts": time.time()}, retain=True)

    async def _run(self) -> None:
        will = aiomqtt.Will(
            self._status_topic, json.dumps({"state": "offline"}), qos=1, retain=True
        )
        async with aiomqtt.Client(
            hostname=self._host,
            port=self._port,
            identifier="fake-lv",
            protocol=aiomqtt.ProtocolVersion.V5,
            will=will,
        ) as client:
            self._client = client
            await client.publish(
                self._status_topic, json.dumps({"state": "online", "ts": time.time()}),
                qos=1, retain=True,
            )
            await client.subscribe(f"tmf/{self.station}/cmd/+", qos=1)
            self._ready.set()
            async for msg in client.messages:
                await self._handle_cmd(client, msg)

    async def _handle_cmd(self, client, msg) -> None:
        req = json.loads(msg.payload)
        props = msg.properties
        reply_topic = getattr(props, "ResponseTopic", None)
        corr = getattr(props, "CorrelationData", None)
        if req.get("op") == "hello.echo":
            result = {"echoed": req.get("args"), "station": self.station, "ts": time.time()}
            reply = {"id": req["id"], "ok": True, "result": result}
        else:
            reply = {"id": req["id"], "ok": False,
                     "error": {"code": "unknown_op", "message": req.get("op"), "detail": ""}}
        out = Properties(PacketTypes.PUBLISH)
        if corr is not None:
            out.CorrelationData = corr
        if reply_topic:
            await client.publish(reply_topic, json.dumps(reply), qos=1, properties=out)

"""Reference LabVIEW Bridge stub, in Python (LABVIEW_BRIDGE.md §12).

This is the *executable contract* for the LabVIEW stub: the real DQMH Bridge VI
must produce byte-identical wire behaviour. It is also runnable as a standalone
process so the round-trip works against a real broker without LabVIEW — point
MQTT Explorer at `tmf/#` and watch it.

Behaviour (BRIDGE §12):
  - connect MQTT5; LWT = status {"state":"offline"} retained.
  - publish status {"state":"online", ...} retained; republish periodically with
    uptime / publish counters / cmd_pending.
  - subscribe cmd/+; reply to hello.echo via response-topic + correlation-data.
  - publish stream/ai ~10 Hz (QoS 0, not retained): {t, seq, values:{ai0}}.
  - publish value/vbus_main retained: {value, ts}.
  - emit a diag event periodically so the bus is visible alongside the rest.

Run:  python -m tools.lv_stub --station st1 --host 127.0.0.1 --port 1883
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import time

import aiomqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties


class LabviewStub:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1883,
        station: str = "st1",
        *,
        stream_hz: float = 10.0,
        value_period: float = 1.0,
        status_period: float = 5.0,
    ) -> None:
        self.host, self.port, self.station = host, port, station
        self.stream_hz = stream_hz
        self.value_period = value_period
        self.status_period = status_period

        self._status_topic = f"tmf/{station}/status"
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._stop = False
        self._t0 = time.time()
        self._seq = 0
        self._diag_seq = 0
        self._publishes = 0

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="lv-stub")
        await asyncio.wait_for(self._ready.wait(), 5)

    async def stop(self) -> None:
        """Graceful stop: announce offline (retained), then disconnect."""
        self._stop = True
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.publish(
                    self._status_topic, json.dumps({"state": "offline", "ts": time.time()}),
                    qos=1, retain=True,
                )
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _run(self) -> None:
        will = aiomqtt.Will(self._status_topic, json.dumps({"state": "offline"}), qos=1, retain=True)
        async with aiomqtt.Client(
            hostname=self.host,
            port=self.port,
            identifier=f"lv-stub-{self.station}",
            protocol=aiomqtt.ProtocolVersion.V5,
            will=will,
        ) as client:
            self._client = client
            await self._publish_status(client)
            await client.subscribe(f"tmf/{self.station}/cmd/+", qos=1)
            producers = [
                asyncio.create_task(self._stream_loop(client)),
                asyncio.create_task(self._value_loop(client)),
                asyncio.create_task(self._status_loop(client)),
            ]
            self._ready.set()
            try:
                async for msg in client.messages:
                    await self._handle_cmd(client, msg)
            finally:
                for p in producers:
                    p.cancel()

    # --- producers ---------------------------------------------------------

    async def _stream_loop(self, client) -> None:
        period = 1.0 / self.stream_hz
        while not self._stop:
            self._seq += 1
            value = round(5.0 + 0.001 * math.sin(self._seq / 10.0), 6)
            await self._pub(client, f"tmf/{self.station}/stream/ai",
                            {"t": time.time(), "seq": self._seq, "values": {"ai0": value}},
                            qos=0, retain=False)
            await asyncio.sleep(period)

    async def _value_loop(self, client) -> None:
        while not self._stop:
            v = round(264.0 + math.sin(time.time()), 3)
            await self._pub(client, f"tmf/{self.station}/value/vbus_main",
                            {"value": v, "ts": time.time()}, qos=1, retain=True)
            await asyncio.sleep(self.value_period)

    async def _status_loop(self, client) -> None:
        while not self._stop:
            await asyncio.sleep(self.status_period)
            await self._publish_status(client)
            await self._emit_diag(client)

    async def _publish_status(self, client) -> None:
        await self._pub(client, self._status_topic, {
            "state": "online",
            "ts": time.time(),
            "uptime_s": round(time.time() - self._t0, 1),
            "publishes": self._publishes,
            "cmd_pending": 0,
        }, qos=1, retain=True)

    async def _emit_diag(self, client) -> None:
        self._diag_seq += 1
        await self._pub(client, f"tmf/{self.station}/diag", {
            "seq": self._diag_seq, "ts": time.time(), "level": "info", "subsystem": "stub",
            "message": "heartbeat", "context": {"uptime_s": round(time.time() - self._t0, 1)},
            "exception": None,
        }, qos=1, retain=False)

    # --- commands ----------------------------------------------------------

    async def _handle_cmd(self, client, msg) -> None:
        try:
            req = json.loads(msg.payload)
        except (json.JSONDecodeError, TypeError):
            return
        props = msg.properties
        reply_topic = getattr(props, "ResponseTopic", None)
        corr = getattr(props, "CorrelationData", None)

        if req.get("op") == "hello.echo":
            reply = {"id": req["id"], "ok": True,
                     "result": {"echoed": req.get("args"), "station": self.station, "ts": time.time()}}
        else:
            reply = {"id": req["id"], "ok": False,
                     "error": {"code": "unknown_op", "message": f"no op {req.get('op')}", "detail": ""}}

        out = Properties(PacketTypes.PUBLISH)
        if corr is not None:
            out.CorrelationData = corr
        if reply_topic:
            await client.publish(reply_topic, json.dumps(reply), qos=1, properties=out)
            self._publishes += 1

    async def _pub(self, client, topic, payload, *, qos, retain) -> None:
        await client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        self._publishes += 1


async def _main_async(args) -> None:
    stub = LabviewStub(args.host, args.port, args.station,
                       stream_hz=args.stream_hz, status_period=args.status_period)
    await stub.start()
    print(f"lv-stub online: tmf/{args.station}/  (broker {args.host}:{args.port})  Ctrl-C to stop")
    try:
        await asyncio.Event().wait()  # run forever
    finally:
        await stub.stop()


def main() -> None:
    p = argparse.ArgumentParser(description="Reference LabVIEW Bridge stub (LABVIEW_BRIDGE.md §12)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--station", default="st1")
    p.add_argument("--stream-hz", type=float, default=10.0)
    p.add_argument("--status-period", type=float, default=5.0)
    args = p.parse_args()
    try:
        asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

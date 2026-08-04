"""DAQ `default` variant — LabVIEW-backed instruments (CORE.md §9 pattern).

Stream control goes out as commands (daq.{signal}.stream.start/stop). Frames
arrive on stream/{signal}, are cached by the bridge (latest-wins, BRIDGE §6) and
fanned out to WS clients via a StreamHub per signal.
"""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.streaming import StreamHub
from modules.daq.api import build_router

SIGNALS = ("ai", "di")


class DefaultDaq:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self._hubs: dict[str, StreamHub] = {s: StreamHub() for s in SIGNALS}
        self._running: dict[str, bool] = {s: False for s in SIGNALS}
        self._values_hub = StreamHub()           # value/{name} -> /instruments/values/ws
        self._values: dict[tuple, dict] = {}      # (station, name) -> latest frame (snapshot)
        self.router = build_router(self)
        self.mqtt_handlers = [(f"stream/{s}", self._make_handler(s)) for s in SIGNALS]
        # Subscribe value/# so the bridge caches retained values (BRIDGE §6) and we
        # fan live updates to the operator window.
        self.mqtt_handlers.append(("value/#", self._on_value))

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultDaq":
        return cls(core, config)

    async def init(self) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        online = bool(self.core.bridge and self.core.bridge.online)
        return Health(
            status=HealthStatus.OK if online else HealthStatus.DEGRADED,
            detail="bridge online" if online else "bridge link not online",
        )

    # --- frame intake (subscribed by the gate via mqtt_handlers) -----------

    @staticmethod
    def _station_of(topic: str) -> str | None:
        parts = topic.split("/")
        return parts[1] if len(parts) > 2 and parts[0] == "tmf" else None

    def _make_handler(self, signal: str):
        def handler(topic: str, payload: dict | None) -> None:
            if payload is not None:
                # Tag with the socket so the WS `?station=` filter works (MULTI_STATION.md §5/§4.6).
                self._hubs[signal].broadcast({**payload, "station": self._station_of(topic)})

        return handler

    def _on_value(self, topic: str, payload: dict | None) -> None:
        # value topic = tmf/{station}/value/{name}; cache latest per (station,name) + fan out.
        if payload is None:
            return
        station = self._station_of(topic)
        name = topic.split("value/", 1)[-1]
        frame = {"name": name, "station": station, **payload}
        self._values[(station, name)] = frame
        self._values_hub.broadcast(frame)

    # --- contract ----------------------------------------------------------

    async def _stream(self, signal: str, action: str, args: dict | None) -> dict:
        reply = await self.core.bridge.request(f"daq.{signal}.stream.{action}", args or {},
                                               station=self.core.station)
        if reply.get("ok"):
            self._running[signal] = action == "start"
        self.core.diag.info("daq", f"{signal} stream {action}", ok=reply.get("ok"))
        return reply

    async def ai_stream_start(self, args: dict | None = None) -> dict:
        return await self._stream("ai", "start", args)

    async def ai_stream_stop(self) -> dict:
        return await self._stream("ai", "stop", None)

    async def di_stream_start(self, args: dict | None = None) -> dict:
        return await self._stream("di", "start", args)

    async def di_stream_stop(self) -> dict:
        return await self._stream("di", "stop", None)

    def latest(self, signal: str) -> dict | None:
        return self.core.bridge.latest(f"stream/{signal}")

    def is_running(self, signal: str) -> bool:
        return self._running.get(signal, False)

    # --- variables (BRIDGE §6 last-value) ----------------------------------

    async def variable_read(self, name: str) -> dict:
        """Prefer the retained value/{name} snapshot; else a variable.read cmd."""
        cached = self.core.bridge.latest(f"value/{name}")
        if cached is not None:
            return cached
        reply = await self.core.bridge.request("variable.read", {"name": name},
                                               station=self.core.station)
        if not reply.get("ok"):
            raise ValueError((reply.get("error") or {}).get("message", "variable.read failed"))
        return reply.get("result", {})

    async def variable_write(self, name: str, value: object) -> dict:
        reply = await self.core.bridge.request("variable.write", {"name": name, "value": value},
                                               station=self.core.station)
        self.core.diag.info("daq", "variable write", name=name, ok=reply.get("ok"))
        return reply

    # --- WS relay ----------------------------------------------------------

    async def stream_ws(self, ws: WebSocket, signal: str) -> None:
        await ws.accept()
        if not self._running.get(signal):
            # Gate on "is the stream running" (BRIDGE §6).
            await ws.close(code=4409, reason="stream not running")
            return
        station = ws.query_params.get("station")   # optional socket filter (§5)
        snapshot = self.latest(signal)  # snapshot-on-join
        if snapshot is not None and not (station and snapshot.get("station") not in (station, None)):
            await ws.send_json(snapshot)
        async with self._hubs[signal].subscription() as q:
            try:
                while True:
                    frame = await q.get()
                    if station and frame.get("station") != station:
                        continue
                    await ws.send_json(frame)
            except WebSocketDisconnect:
                pass

    async def stream_values_ws(self, ws: WebSocket) -> None:
        """Live station variable values for the operator window. Snapshot-on-join
        (every cached value), then live value/{name} updates. `?station=` filters (§5)."""
        await ws.accept()
        station = ws.query_params.get("station")
        for frame in list(self._values.values()):
            if station and frame.get("station") != station:
                continue
            await ws.send_json(frame)
        async with self._values_hub.subscription() as q:
            try:
                while True:
                    frame = await q.get()
                    if station and frame.get("station") != station:
                        continue
                    await ws.send_json(frame)
            except WebSocketDisconnect:
                pass

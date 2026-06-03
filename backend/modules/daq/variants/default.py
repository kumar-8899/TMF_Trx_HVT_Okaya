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
        self.router = build_router(self)
        self.mqtt_handlers = [(f"stream/{s}", self._make_handler(s)) for s in SIGNALS]

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

    def _make_handler(self, signal: str):
        def handler(_topic: str, payload: dict | None) -> None:
            if payload is not None:
                self._hubs[signal].broadcast(payload)

        return handler

    # --- contract ----------------------------------------------------------

    async def _stream(self, signal: str, action: str, args: dict | None) -> dict:
        reply = await self.core.bridge.request(f"daq.{signal}.stream.{action}", args or {})
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

    # --- WS relay ----------------------------------------------------------

    async def stream_ws(self, ws: WebSocket, signal: str) -> None:
        await ws.accept()
        if not self._running.get(signal):
            # Gate on "is the stream running" (BRIDGE §6).
            await ws.close(code=4409, reason="stream not running")
            return
        snapshot = self.latest(signal)  # snapshot-on-join
        if snapshot is not None:
            await ws.send_json(snapshot)
        async with self._hubs[signal].subscription() as q:
            try:
                while True:
                    await ws.send_json(await q.get())
            except WebSocketDisconnect:
                pass

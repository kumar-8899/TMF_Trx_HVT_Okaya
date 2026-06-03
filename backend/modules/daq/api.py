"""DAQ router (CORE.md §9). Absolute paths — the module owns /instruments/daq
(and /variables in P1.3), so it mounts at an empty prefix.

REST + WS framing follows LABVIEW_BRIDGE.md §4/§9 (near pass-through)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket

from core.services.bridge import BridgeError, BridgeTimeout

_BASE = "/instruments/daq"


async def _guard(coro):
    try:
        return await coro
    except BridgeTimeout as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except BridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["daq"])

    def add_signal(signal: str) -> None:
        starter = getattr(module, f"{signal}_stream_start")
        stopper = getattr(module, f"{signal}_stream_stop")

        @router.post(f"{_BASE}/{signal}/stream/start")
        async def start(args: dict | None = None, _starter=starter) -> dict:
            return await _guard(_starter(args))

        @router.post(f"{_BASE}/{signal}/stream/stop")
        async def stop(_stopper=stopper) -> dict:
            return await _guard(_stopper())

        @router.get(f"{_BASE}/{signal}/latest")
        async def latest(_signal=signal) -> dict:
            frame = module.latest(_signal)
            if frame is None:
                raise HTTPException(status_code=404, detail=f"no {_signal} frame yet")
            return frame

        @router.websocket(f"{_BASE}/{signal}/stream/ws")
        async def stream_ws(websocket: WebSocket, _signal=signal) -> None:
            await module.stream_ws(websocket, _signal)

    for sig in ("ai", "di"):
        add_signal(sig)

    return router

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
        # `signal`, `starter`, `stopper` are per-call locals of add_signal, so the
        # handlers close over them safely — do NOT push them in as parameter
        # defaults. FastAPI deep-copies a handler's default values per request; a
        # bound method default would drag in the whole module graph (incl. the
        # live sqlite3.Connection) and crash with an unpicklable-object TypeError.
        starter = getattr(module, f"{signal}_stream_start")
        stopper = getattr(module, f"{signal}_stream_stop")

        @router.post(f"{_BASE}/{signal}/stream/start")
        async def start(args: dict | None = None) -> dict:
            return await _guard(starter(args))

        @router.post(f"{_BASE}/{signal}/stream/stop")
        async def stop() -> dict:
            return await _guard(stopper())

        @router.get(f"{_BASE}/{signal}/latest")
        async def latest() -> dict:
            frame = module.latest(signal)
            if frame is None:
                raise HTTPException(status_code=404, detail=f"no {signal} frame yet")
            return frame

        @router.websocket(f"{_BASE}/{signal}/stream/ws")
        async def stream_ws(websocket: WebSocket) -> None:
            await module.stream_ws(websocket, signal)

    for sig in ("ai", "di"):
        add_signal(sig)

    @router.websocket("/instruments/values/ws")
    async def values_ws(websocket: WebSocket) -> None:
        await module.stream_values_ws(websocket)

    @router.get("/variables/{name}/value")
    async def read_variable(name: str) -> dict:
        try:
            return await module.variable_read(name)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except BridgeTimeout as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except BridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.put("/variables/{name}/value")
    async def write_variable(name: str, body: dict) -> dict:
        if "value" not in body:
            raise HTTPException(status_code=422, detail="body must include 'value'")
        return await _guard(module.variable_write(name, body["value"]))

    return router

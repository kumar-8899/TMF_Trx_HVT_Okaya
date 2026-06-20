"""Runs router (CORE.md §7). Absolute paths; mounts at an empty prefix
(/ws/station + /diagnostics/stream are added in P1.5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket

from core.services.bridge import BridgeError, BridgeTimeout
from core.services.interlock import InterlockError
from core.services.security import require_permission
from modules.runs.acquisition import AcquisitionError


def _operator(request: Request) -> str | None:
    """Best-effort: the authenticated user who started the run (for analytics).
    Does not gate the call — absent/invalid token just means no operator stamp."""
    try:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return request.app.state.auth.verify(header[7:].strip()).subject
    except Exception:  # noqa: BLE001
        return None
    return None


async def _guard(coro):
    try:
        return await coro
    except InterlockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AcquisitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BridgeTimeout as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except BridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["runs"])

    @router.get("/runs/acquisition")
    async def acquisition() -> dict:
        return module.acquisition_config()

    @router.get("/runs/config")
    async def run_config() -> dict:
        return module.profile()

    @router.post("/runs/start")
    async def run_start(request: Request, params: dict | None = None) -> dict:
        body = dict(params or {})
        op = _operator(request)
        if op:
            body.setdefault("operator", op)
        return await _guard(module.run_start(body))

    @router.post("/runs/abort")
    async def run_abort() -> dict:
        return await _guard(module.run_abort())

    @router.post("/runs/reset-data", dependencies=[Depends(require_permission("SYSTEM.RESET_DATA"))])
    async def reset_data() -> dict:
        return await module.reset_data()

    @router.get("/runs")
    async def list_runs(since: float | None = None, limit: int | None = None) -> list[dict]:
        return await module.list_runs(since=since, limit=limit)

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict:
        run = await module.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no run '{run_id}'")
        return run

    @router.websocket("/ws/station")
    async def station_ws(websocket: WebSocket) -> None:
        await module.station_ws(websocket)

    @router.websocket("/diagnostics/stream")
    async def diagnostics_ws(websocket: WebSocket) -> None:
        await module.diag_ws(websocket)

    return router

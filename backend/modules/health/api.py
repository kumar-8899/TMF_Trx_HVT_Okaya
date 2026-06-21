"""Health router (prefix /health). Tiered perms: health.view / health.run."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket

from core.services.security import require_permission

_VIEW = [Depends(require_permission("HEALTH.VIEW"))]
_RUN = [Depends(require_permission("HEALTH.RUN"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health/checks", dependencies=_VIEW)
    async def list_checks() -> list[dict]:
        return module.list_checks()

    @router.get("/health/suites", dependencies=_VIEW)
    async def list_suites() -> list[dict]:
        return module.list_suites()

    @router.post("/health/checks/{check_id}/run", dependencies=_RUN)
    async def run_one(check_id: str) -> dict:
        try:
            return {"health_run_id": await module.run(check_ids=[check_id])}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/health/run", dependencies=_RUN)
    async def run(body: dict) -> dict:
        try:
            return {"health_run_id": await module.run(
                suite=body.get("suite"), check_ids=body.get("check_ids"),
                mode=body.get("mode", "serial"))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/health/run/{hid}/abort", dependencies=_RUN, status_code=204)
    async def abort(hid: str):
        module.abort(hid)

    @router.get("/health/runs", dependencies=_VIEW)
    async def list_runs(since: float | None = None, limit: int | None = None,
                        trigger: str | None = None) -> list[dict]:
        return await module.list_runs(since=since, limit=limit, trigger=trigger)

    @router.get("/health/current", dependencies=_VIEW)
    async def current(trigger: str | None = None) -> dict | None:
        return await module.current(trigger=trigger)

    @router.get("/health/runs/{hid}", dependencies=_VIEW)
    async def get_run(hid: str) -> dict:
        run = await module.get_run(hid)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no health run '{hid}'")
        return run

    @router.websocket("/health/run/{hid}/stream")
    async def stream(websocket: WebSocket, hid: str) -> None:
        await module.stream_ws(websocket, hid)

    return router

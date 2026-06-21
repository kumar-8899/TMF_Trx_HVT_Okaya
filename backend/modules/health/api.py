"""Health router (prefix /health). Tiered perms: health.view / health.run."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket

from core.services.auth_verify import Principal
from core.services.bridge import BridgeError, BridgeTimeout
from core.services.security import require_permission

_VIEW = [Depends(require_permission("HEALTH.VIEW"))]
_RUN = [Depends(require_permission("HEALTH.RUN"))]
_MAINT = Depends(require_permission("HEALTH.MAINTENANCE"))


async def _bridge_guard(coro):
    try:
        return await coro
    except BridgeTimeout as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except BridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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

    # --- known issues + suggestions (§7) -----------------------------------

    @router.get("/health/known-issues", dependencies=_VIEW)
    async def known_issues(q: str | None = None, check_id: str | None = None) -> list[dict]:
        return module.list_known_issues(q=q, check_id=check_id)

    @router.get("/health/known-issues/{issue_id}", dependencies=_VIEW)
    async def known_issue(issue_id: str) -> dict:
        iss = module.get_known_issue(issue_id)
        if iss is None:
            raise HTTPException(status_code=404, detail=f"no known issue '{issue_id}'")
        return iss

    @router.get("/health/suggestions", dependencies=_VIEW)
    async def suggestions(since: float | None = None, matched: bool | None = None) -> list[dict]:
        return await module.list_suggestions(since=since, matched=matched)

    @router.post("/health/suggestions/{sid}/ack", dependencies=_RUN, status_code=204)
    async def ack_suggestion(sid: str, body: dict):
        if not await module.ack_suggestion(sid, (body or {}).get("outcome", "")):
            raise HTTPException(status_code=404, detail=f"no suggestion '{sid}'")

    # --- maintenance (proxied to the LabVIEW authority, §8) ----------------

    @router.get("/health/maintenance", dependencies=_VIEW)
    async def maintenance_state() -> dict:
        return module.maintenance_state()

    @router.post("/health/maintenance/enter")
    async def maintenance_enter(body: dict, principal: Principal = _MAINT) -> dict:
        return await _bridge_guard(module.maintenance_enter(principal.subject, (body or {}).get("reason")))

    @router.post("/health/maintenance/exit")
    async def maintenance_exit(principal: Principal = _MAINT) -> dict:
        return await _bridge_guard(module.maintenance_exit(principal.subject))

    @router.websocket("/health/run/{hid}/stream")
    async def stream(websocket: WebSocket, hid: str) -> None:
        await module.stream_ws(websocket, hid)

    return router

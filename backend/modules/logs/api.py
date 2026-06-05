"""Logs router (LOGS.md §7). Mounted under /logs (manifest api_prefix).

Read = DIAGNOSTICS.VIEW; DELETE = DIAGNOSTICS.PURGE (reconciled to permission-first
from the doc's VIEWER/OPERATOR/ADMIN). Errors are RFC-7807 via web.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.services.security import require_permission

_VIEW = [Depends(require_permission("DIAGNOSTICS.VIEW"))]
_PURGE = [Depends(require_permission("DIAGNOSTICS.PURGE"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["logs"])

    @router.get("/errors", dependencies=_VIEW)
    async def errors(
        since: float | None = None, until: float | None = None,
        level: str | None = None, subsystem: str | None = None,
        limit: int = 200, cursor: str | None = None,
    ) -> dict:
        return await module.query_errors(
            since=since, until=until, level=level, subsystem=subsystem, limit=limit, cursor=cursor
        )

    @router.get("/actions", dependencies=_VIEW)
    async def actions(
        since: float | None = None, until: float | None = None,
        user: str | None = None, action: str | None = None, result: str | None = None,
        limit: int = 200, cursor: str | None = None,
    ) -> dict:
        return await module.query_actions(
            since=since, until=until, user=user, action=action, result=result,
            limit=limit, cursor=cursor,
        )

    @router.get("/stats", dependencies=_VIEW)
    async def stats(since: float | None = None) -> dict:
        return await module.stats(since=since)

    @router.delete("/errors", dependencies=_PURGE)
    async def delete_errors(before: float) -> dict:
        return {"deleted": await module.delete_errors(before)}

    @router.delete("/actions", dependencies=_PURGE)
    async def delete_actions(before: float) -> dict:
        return {"deleted": await module.delete_actions(before)}

    return router

"""Report router (prefix /reports). Reads = REPORT.VIEW; export = REPORT.EXPORT."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.services.security import require_permission

_VIEW = [Depends(require_permission("REPORT.VIEW"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["report"])

    @router.get("", dependencies=_VIEW)
    async def list_reports(
        since: float | None = None, until: float | None = None,
        recipe_id: str | None = None, result: str | None = None,
        limit: int = 200, cursor: str | None = None,
    ) -> dict:
        return await module.list_reports(since=since, until=until, recipe_id=recipe_id,
                                          result=result, limit=limit, cursor=cursor)

    @router.get("/{run_id}", dependencies=_VIEW)
    async def get_report(run_id: str) -> dict:
        report = await module.get_report(run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"no report for run '{run_id}'")
        return report

    return router

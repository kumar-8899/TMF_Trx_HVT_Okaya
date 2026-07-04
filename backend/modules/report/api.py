"""Report router (prefix /reports). Reads = REPORT.VIEW; export = REPORT.EXPORT."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from core.services.security import require_permission

_VIEW = [Depends(require_permission("REPORT.VIEW"))]
_EXPORT = [Depends(require_permission("REPORT.EXPORT"))]
_SETTINGS = [Depends(require_permission("SYSTEM.SETTINGS"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["report"])

    @router.get("", dependencies=_VIEW)
    async def list_reports(
        since: float | None = None, until: float | None = None,
        recipe_id: str | None = None, result: str | None = None,
        model: str | None = None, shift: str | None = None,
        limit: int = 200, cursor: str | None = None,
    ) -> dict:
        offset = int(cursor) if cursor and cursor.isdigit() else 0
        return await module.list_reports(since=since, until=until, recipe_id=recipe_id,
                                          result=result, model=model, shift=shift,
                                          limit=limit, offset=offset)

    # --- report DB config (professional store) — super_admin ---------------
    # Defined BEFORE /{run_id} so 'db-config' isn't captured as a run id.

    @router.get("/db-config", dependencies=_SETTINGS)
    async def get_db_config() -> dict:
        return await module.get_db_config()

    @router.put("/db-config", dependencies=_SETTINGS)
    async def set_db_config(body: dict) -> dict:
        return await module.set_db_config(body or {})

    @router.post("/db-config/test", dependencies=_SETTINGS)
    async def test_db_config(body: dict | None = None) -> dict:
        return await module.test_db_config(body or {})

    @router.get("/analytics", dependencies=_VIEW)
    async def analytics(since: float | None = None, until: float | None = None,
                        recipe_id: str | None = None) -> dict:
        return await module.analytics(since=since, until=until, recipe_id=recipe_id)

    @router.get("/analytics/dashboard", dependencies=_VIEW)
    async def analytics_dashboard(
        since: float | None = None, until: float | None = None,
        model: str | None = None, operator: str | None = None, shift: str | None = None,
    ) -> dict:
        return await module.dashboard(since=since, until=until, model=model, operator=operator, shift=shift)

    @router.get("/{run_id}", dependencies=_VIEW)
    async def get_report(run_id: str) -> dict:
        report = await module.get_report(run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"no report for run '{run_id}'")
        return report

    @router.get("/{run_id}/export", dependencies=_EXPORT)
    async def export_report(run_id: str, format: str = "json") -> Response:
        try:
            data = await module.export(run_id, format)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"no report for run '{run_id}'") from exc
        media = "text/csv" if format == "csv" else "application/json"
        return Response(content=data, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="report-{run_id}.{format}"'})

    return router

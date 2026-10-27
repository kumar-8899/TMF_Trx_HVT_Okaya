"""Okaya MES router. Settings, table checks and the preview need SYSTEM.SETTINGS (like the framework MES
page); write-failure alerts need TEST.RUN — the operator is who must see and act on a failed hand-off."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.services.auth_verify import Principal
from core.services.security import require_permission

_ADMIN = [Depends(require_permission("SYSTEM.SETTINGS"))]
_OPERATOR = require_permission("TEST.RUN")


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["okaya_mes"])

    @router.get("/okaya-mes/status", dependencies=_ADMIN)
    async def status() -> dict:
        return await module.status()

    @router.get("/okaya-mes/config", dependencies=_ADMIN)
    async def get_config() -> dict:                      # password never leaves the station
        return module.get_config()

    @router.put("/okaya-mes/config", dependencies=_ADMIN)
    async def set_config(body: dict) -> dict:
        return await module.set_config(body or {})

    # --- stateless helpers fed with the UI's draft (blank password = keep the stored one) --------

    @router.post("/okaya-mes/db/test", dependencies=_ADMIN)
    async def db_test(body: dict) -> dict:
        return await module.db_test(body.get("connection"))

    @router.post("/okaya-mes/db/databases", dependencies=_ADMIN)
    async def db_databases(body: dict) -> dict:
        return await module.db_databases(body.get("connection"))

    @router.post("/okaya-mes/db/tables", dependencies=_ADMIN)
    async def db_tables(body: dict) -> dict:
        return await module.db_tables(body.get("connection"), body.get("database"))

    @router.post("/okaya-mes/table/check", dependencies=_ADMIN)
    async def check_table(body: dict) -> dict:
        return await module.check_table(body.get("connection"), body.get("database"), body.get("table"))

    @router.post("/okaya-mes/table/create", dependencies=_ADMIN)
    async def create_table(body: dict) -> dict:
        return await module.create_table(body.get("connection"), body.get("database"), body.get("table"))

    @router.get("/okaya-mes/preview/{run_id}", dependencies=_ADMIN)
    async def preview(run_id: str) -> dict:
        try:
            return await module.preview(run_id)
        except Exception as exc:  # noqa: BLE001 — unknown run id etc.
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/okaya-mes/runs/{run_id}/send", dependencies=_ADMIN)
    async def send_run(run_id: str) -> dict:
        try:
            return await module.send_run(run_id)
        except Exception as exc:  # noqa: BLE001 — surfaced to the admin, not a 500
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- write failures: persisted status ---------------------------------------------------------

    @router.get("/okaya-mes/alerts", dependencies=[Depends(_OPERATOR)])
    async def alerts() -> dict:
        items = await module.alerts()
        return {"items": items, "count": len(items)}

    @router.post("/okaya-mes/alerts/{run_id}/retry", dependencies=[Depends(_OPERATOR)])
    async def alert_retry(run_id: str) -> dict:
        return await module.alert_retry(run_id)

    @router.post("/okaya-mes/alerts/{run_id}/dismiss")
    async def alert_dismiss(run_id: str, who: Principal = Depends(_OPERATOR)) -> dict:
        return await module.alert_dismiss(run_id, by=who.subject)

    return router

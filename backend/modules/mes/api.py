"""MES router. Settings + the database configuration "process" (SYSTEM.SETTINGS); outbound-failure
alerts (TEST.RUN — the operator is who must see and act on a failed hand-off)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.services.auth_verify import Principal
from core.services.security import require_permission

_ADMIN = [Depends(require_permission("SYSTEM.SETTINGS"))]
_OPERATOR = require_permission("TEST.RUN")


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["mes"])

    @router.get("/mes/status", dependencies=_ADMIN)
    async def status() -> dict:
        return await module.status()

    @router.put("/mes/config", dependencies=_ADMIN)
    async def set_config(body: dict) -> dict:
        try:
            return await module.set_config(
                gate_enabled=body.get("gate_enabled"), publish_enabled=body.get("publish_enabled"),
                provider=body.get("provider"), on_missing=body.get("on_missing"),
                on_error=body.get("on_error"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- database settings (passwords redacted on read; blank password on write = keep) ----------

    @router.get("/mes/db-config", dependencies=_ADMIN)
    async def get_db_config() -> dict:
        return module.get_db_config()

    @router.put("/mes/db-config", dependencies=_ADMIN)
    async def set_db_config(body: dict) -> dict:
        return await module.set_db_config(body or {})

    # --- the configuration process: stateless helpers fed with the UI's draft ---------------------
    # Listing helpers never fail the request: {ok:false, items:[], detail} -> the UI offers manual entry.

    def _side(body: dict) -> str:
        side = body.get("side", "inbound")
        if side not in ("inbound", "outbound"):
            raise HTTPException(status_code=422, detail="side must be 'inbound' or 'outbound'")
        return side

    @router.post("/mes/db/test", dependencies=_ADMIN)
    async def db_test(body: dict) -> dict:
        return await module.db_test(_side(body), body.get("connection"), bool(body.get("same_as_inbound")))

    @router.post("/mes/db/databases", dependencies=_ADMIN)
    async def db_databases(body: dict) -> dict:
        return await module.db_databases(_side(body), body.get("connection"), bool(body.get("same_as_inbound")))

    @router.post("/mes/db/tables", dependencies=_ADMIN)
    async def db_tables(body: dict) -> dict:
        return await module.db_tables(_side(body), body.get("connection"), body.get("database"),
                                      bool(body.get("same_as_inbound")))

    @router.post("/mes/db/columns", dependencies=_ADMIN)
    async def db_columns(body: dict) -> dict:
        return await module.db_columns(_side(body), body.get("connection"), body.get("database"),
                                       body.get("table") or "", bool(body.get("same_as_inbound")))

    @router.post("/mes/db/values", dependencies=_ADMIN)
    async def db_values(body: dict) -> dict:
        return await module.db_values(body.get("connection"), body.get("database"),
                                      body.get("table") or "", body.get("column") or "")

    @router.post("/mes/db/verify", dependencies=_ADMIN)
    async def db_verify(body: dict) -> dict:
        return await module.db_verify(_side(body), body.get("connection"), body.get("database"),
                                      body.get("table") or "", list(body.get("columns") or []),
                                      bool(body.get("same_as_inbound")))

    @router.post("/mes/db/inbound/check", dependencies=_ADMIN)
    async def inbound_check(body: dict) -> dict:
        if not str(body.get("serial") or "").strip():
            raise HTTPException(status_code=422, detail="enter a serial number to try")
        return await module.inbound_check(str(body["serial"]).strip(), body.get("inbound"))

    @router.post("/mes/db/outbound/validate", dependencies=_ADMIN)
    async def outbound_validate(body: dict) -> dict:
        return await module.outbound_validate(body.get("outbound"))

    @router.post("/mes/db/outbound/ensure", dependencies=_ADMIN)
    async def outbound_ensure(body: dict) -> dict:
        return await module.outbound_ensure(body.get("outbound"), bool(body.get("add_missing")))

    # --- outbound failures: persisted status, surfaced on every screen ---------------------------

    @router.get("/mes/alerts", dependencies=[Depends(_OPERATOR)])
    async def alerts() -> dict:
        items = await module.alerts()
        return {"items": items, "count": len(items)}

    @router.post("/mes/alerts/{run_id}/retry", dependencies=[Depends(_OPERATOR)])
    async def alert_retry(run_id: str) -> dict:
        return await module.alert_retry(run_id)

    @router.post("/mes/alerts/{run_id}/dismiss")
    async def alert_dismiss(run_id: str, who: Principal = Depends(_OPERATOR)) -> dict:
        return await module.alert_dismiss(run_id, by=who.subject)

    return router

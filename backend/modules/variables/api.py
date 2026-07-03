"""variables router (/variables). Reads gated CONFIG.VIEW; writes are a hands-on
hardware action gated HEALTH.MAINTENANCE (the maintenance/manual path). LabVIEW uses
the bridge verbs, not these routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.services.security import require_permission
from instrumentlib.errors import InstrumentError, NotConnected
from modules.variables.engine import VariableError

_VIEW = [Depends(require_permission("CONFIG.VIEW"))]
_WRITE = [Depends(require_permission("HEALTH.MAINTENANCE"))]


async def _guard(coro):
    try:
        return await coro
    except VariableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotConnected as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InstrumentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["variables"])
    eng = module.engine

    @router.get("/variables", dependencies=_VIEW)
    async def list_variables() -> list[dict]:
        return eng.list()

    @router.get("/variables/{name}/value", dependencies=_VIEW)
    async def read_variable(name: str) -> dict:
        return await _guard(eng.read(name))

    @router.put("/variables/{name}/value", dependencies=_WRITE)
    async def write_variable(name: str, body: dict) -> dict:
        if "value" not in (body or {}):
            raise HTTPException(status_code=422, detail="value required")
        return await _guard(eng.write(name, body["value"]))

    @router.post("/variables/read", dependencies=_VIEW)
    async def read_many(body: dict) -> dict:
        return await _guard(eng.read_many((body or {}).get("names", [])))

    @router.post("/variables/write", dependencies=_WRITE)
    async def write_many(body: dict) -> dict:
        return await _guard(eng.write_many((body or {}).get("values", {})))

    return router

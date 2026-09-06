"""variables router (/variables). Reads gated CONFIG.VIEW; variable writes are a
hands-on hardware action gated HEALTH.MAINTENANCE (the maintenance/manual path). The
Instrument Test Bench command path (`/instances/{id}/call`) is super_admin-only. LabVIEW
uses the bridge verbs, not these routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket

from core.services.security import require_permission, require_role
from instrumentlib.errors import InstrumentError, NotConnected, NotSupported
from modules.variables.engine import VariableError

_VIEW = [Depends(require_permission("CONFIG.VIEW"))]
_WRITE = [Depends(require_permission("HEALTH.MAINTENANCE"))]
_TESTBENCH = [Depends(require_role("super_admin"))]   # Test Bench manual command path
_MAP_EDIT = [Depends(require_role("super_admin"))]    # variable-map authoring


async def _guard(coro):
    try:
        return await coro
    except VariableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotSupported as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotConnected as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InstrumentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _map_guard(coro):
    from modules.variables.bindings import BindingError
    from modules.variables.variants.default import BindingUnknownInstance
    try:
        return await coro
    except BindingUnknownInstance as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["variables"])
    eng = module.engine

    @router.get("/variables", dependencies=_VIEW)
    async def list_variables(station: str | None = None) -> list[dict]:
        return eng.list(station)

    @router.get("/variables/libraries", dependencies=_VIEW)
    async def libraries() -> dict:
        return module.libraries()

    @router.get("/variables/capabilities", dependencies=_VIEW)
    async def capabilities() -> dict:
        return module.capabilities()

    @router.get("/variables/instances", dependencies=_VIEW)
    async def instances() -> list[dict]:
        return module.instance_status()

    # Live station-variable values for the operator window (Runs/Maintenance live-values panel).
    # Controller-agnostic — see variants/default.py's stream_values_ws docstring. No permission
    # dependency: WebSocket routes don't support FastAPI `dependencies=`; the values themselves
    # carry nothing sensitive beyond what CONFIG.VIEW already exposes via the REST endpoints above.
    @router.websocket("/instruments/values/ws")
    async def values_ws(websocket: WebSocket) -> None:
        await module.stream_values_ws(websocket)

    # --- variable-map editor (bindings) ------------------------------------

    @router.get("/variables/bindings", dependencies=_VIEW)
    async def list_bindings(station: str | None = None) -> list[dict]:
        from modules.variables.bindings import BindingError
        try:
            return module.list_bindings(station)
        except BindingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/variables/bindable/{instance_id}", dependencies=_VIEW)
    async def bindable(instance_id: str) -> dict:
        from modules.variables.variants.default import BindingUnknownInstance
        try:
            return module.bindable(instance_id)
        except BindingUnknownInstance as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/variables/bindings", dependencies=_MAP_EDIT, status_code=201)
    async def create_binding(body: dict) -> dict:
        name = (body or {}).get("name", "")
        return await _map_guard(module.save_binding(name, body, is_new=True))

    @router.put("/variables/bindings/{name}", dependencies=_MAP_EDIT)
    async def update_binding(name: str, body: dict) -> dict:
        return await _map_guard(module.save_binding(name, body, is_new=False))

    @router.delete("/variables/bindings/{name}", dependencies=_MAP_EDIT, status_code=204)
    async def delete_binding(name: str, station: str | None = None):
        if not await module.delete_binding(name, station):
            raise HTTPException(status_code=404, detail=f"no editable binding '{name}'")

    @router.post("/variables/instances/{instance_id}/call", dependencies=_TESTBENCH)
    async def call(instance_id: str, body: dict) -> dict:
        if not (body or {}).get("method"):
            raise HTTPException(status_code=422, detail="method required")
        return await _guard(module.call(instance_id, body["method"], body.get("args")))

    @router.get("/variables/{name}/value", dependencies=_VIEW)
    async def read_variable(name: str, station: str | None = None) -> dict:
        return await _guard(eng.read(name, station))

    @router.put("/variables/{name}/value", dependencies=_WRITE)
    async def write_variable(name: str, body: dict) -> dict:
        if "value" not in (body or {}):
            raise HTTPException(status_code=422, detail="value required")
        return await _guard(eng.write(name, body["value"], (body or {}).get("station")))

    @router.post("/variables/read", dependencies=_VIEW)
    async def read_many(body: dict) -> dict:
        b = body or {}
        return await _guard(eng.read_many(b.get("names", []), b.get("station")))

    @router.post("/variables/write", dependencies=_WRITE)
    async def write_many(body: dict) -> dict:
        b = body or {}
        return await _guard(eng.write_many(b.get("values", {}), b.get("station")))

    return router

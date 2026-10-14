"""variables router (/variables). Reads gated CONFIG.VIEW; variable writes are a
hands-on hardware action gated HEALTH.MAINTENANCE (the maintenance/manual path). The
Instrument Test Bench command path (`/instances/{id}/call`) is super_admin-only. LabVIEW
uses the bridge verbs, not these routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket

from core.services.security import current_principal, require_authenticated, require_permission, require_role
from instrumentlib.errors import InstrumentError, NotConnected, NotSupported
from modules.variables.engine import VariableError

_VIEW = [Depends(require_permission("CONFIG.VIEW"))]
_WRITE = [Depends(require_permission("HEALTH.MAINTENANCE"))]
_TESTBENCH = [Depends(require_role("super_admin"))]   # Test Bench manual command path
_MAP_EDIT = [Depends(require_role("super_admin"))]    # variable-map authoring
_CALIBRATE = Depends(require_permission("MAINTENANCE.CALIBRATE"))   # CALIBRATION.md


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

    # Connection STATUS only (id, library, capabilities, state, simulated - no params) is every
    # signed-in role's to see, even with CONFIG.VIEW removed (X8); instrument CONFIG stays CONFIG.VIEW.
    @router.get("/variables/instances", dependencies=[Depends(require_authenticated())])
    async def instances() -> list[dict]:
        await module.refresh_instance_status()
        return module.instance_status()

    # Live station-variable values for the operator window (Runs/Maintenance live-values panel).
    # Controller-agnostic — see variants/default.py's stream_values_ws docstring. No permission
    # dependency: WebSocket routes don't support FastAPI `dependencies=`; the values themselves
    # carry nothing sensitive beyond what CONFIG.VIEW already exposes via the REST endpoints above.
    @router.websocket("/instruments/values/ws")
    async def values_ws(websocket: WebSocket) -> None:
        await module.stream_values_ws(websocket)

    # --- calibration (docs/contracts/CALIBRATION.md) -----------------------
    # All gated MAINTENANCE.CALIBRATE (not HEALTH.MAINTENANCE: calibrating changes every later
    # measurement, so it is a separate, auditable grant).

    async def _cal(coro):
        from core.services.calibration import CalibrationError
        from modules.variables.calibration import CalibrationUnavailable
        try:
            return await coro
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown signal {exc}") from exc
        except CalibrationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except CalibrationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except VariableError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except NotConnected as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except InstrumentError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/calibration/signals")
    async def cal_signals(station: str | None = None, _=_CALIBRATE) -> list[dict]:
        from core.services.calibration import CalibrationError
        try:
            return module.calibration.list_signals(station)
        except CalibrationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/calibration/fit")
    async def cal_fit(body: dict, _=_CALIBRATE) -> dict:
        from core.services.calibration import CalibrationError, fit_linear
        try:
            return fit_linear((body or {}).get("points") or [])
        except CalibrationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/calibration/{name}/raw")
    async def cal_raw(name: str, body: dict | None = None, _=_CALIBRATE) -> dict:
        return await _cal(module.calibration.read_raw(name, (body or {}).get("station")))

    @router.post("/calibration/{name}/drive")
    async def cal_drive(name: str, body: dict, _=_CALIBRATE) -> dict:
        if "raw" not in (body or {}):
            raise HTTPException(status_code=422, detail="raw required")
        try:
            raw = float(body["raw"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="raw must be a number") from None
        return await _cal(module.calibration.drive_raw(name, raw, body.get("station")))

    @router.post("/calibration/{name}/apply")
    async def cal_apply(name: str, body: dict, request: Request, _=_CALIBRATE) -> dict:
        return await _cal(module.calibration.apply(
            name, (body or {}).get("points") or [], (body or {}).get("station"),
            current_principal(request).subject))

    @router.delete("/calibration/{name}")
    async def cal_reset(name: str, request: Request, station: str | None = None,
                        _=_CALIBRATE) -> dict:
        return await _cal(module.calibration.reset(
            name, station, current_principal(request).subject))

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

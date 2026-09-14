"""config router (prefix /config). Tiered perms: config.view / config.edit."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.services.security import require_permission

_VIEW = [Depends(require_permission("CONFIG.VIEW"))]
_EDIT = [Depends(require_permission("CONFIG.EDIT"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["config"])

    def _guard(coro):
        from modules.config.variants.default import ConfigError

        async def run():
            try:
                return await coro
            except ConfigError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return run()

    @router.get("/config/transports", dependencies=_VIEW)
    async def transports() -> list[dict]:
        return module.transports()

    # --- shifts (business day + shift labels) ------------------------------

    @router.get("/config/shift", dependencies=_VIEW)
    async def get_shift() -> dict:
        return await module.get_shift_config()

    @router.put("/config/shift", dependencies=_EDIT)
    async def set_shift(body: dict) -> dict:
        return await _guard(module.set_shift_config(body))

    @router.get("/config/shift/current", dependencies=_VIEW)
    async def current_shift() -> dict:
        return await module.current_shift()

    # --- barcode ------------------------------------------------------------

    @router.get("/config/barcode", dependencies=_VIEW)
    async def get_barcode() -> dict:
        return await module.get_barcode_config()

    @router.put("/config/barcode", dependencies=_EDIT)
    async def set_barcode(body: dict) -> dict:
        return await _guard(module.set_barcode_config(body))

    @router.get("/config/instruments", dependencies=_VIEW)
    async def list_instruments() -> list[dict]:
        return await module.list_instruments()

    @router.post("/config/instruments", dependencies=_EDIT, status_code=201)
    async def create_instrument(body: dict) -> dict:
        return await _guard(module.create_instrument(body))

    # test accepts a saved id or an ad-hoc {transport, params}; probe, not mutate.
    @router.post("/config/instruments/test", dependencies=_VIEW)
    async def test_connection(body: dict) -> dict:
        return await _guard(module.test_connection(body))

    @router.get("/config/instruments/{iid}", dependencies=_VIEW)
    async def get_instrument(iid: str) -> dict:
        inst = await module.get_instrument(iid)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"no instrument '{iid}'")
        return inst

    @router.put("/config/instruments/{iid}", dependencies=_EDIT)
    async def update_instrument(iid: str, body: dict) -> dict:
        return await _guard(module.update_instrument(iid, body))

    @router.delete("/config/instruments/{iid}", dependencies=_EDIT, status_code=204)
    async def delete_instrument(iid: str):
        if not await module.delete_instrument(iid):
            raise HTTPException(status_code=404, detail=f"no instrument '{iid}'")

    return router

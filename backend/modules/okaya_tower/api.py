"""Tower-light router: view/edit the buzzer + lamp settings, and a wiring self-test. Admin only
(SYSTEM.SETTINGS), like the other configuration pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.services.security import require_permission

_ADMIN = [Depends(require_permission("SYSTEM.SETTINGS"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["okaya_tower"])

    @router.get("/okaya-tower/status", dependencies=_ADMIN)
    async def status() -> dict:
        return await module.status()

    @router.get("/okaya-tower/config", dependencies=_ADMIN)
    async def get_config() -> dict:
        return module.get_config()

    @router.put("/okaya-tower/config", dependencies=_ADMIN)
    async def set_config(body: dict) -> dict:
        return await module.set_config(body or {})

    @router.post("/okaya-tower/test", dependencies=_ADMIN)
    async def self_test(body: dict) -> dict:
        """Drive one tower output on/off now, to check wiring: {signal: green|red|buzzer, on: bool}."""
        return await module.self_test(body or {})

    return router

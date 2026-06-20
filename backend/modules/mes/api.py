"""MES router. Status + runtime toggle (Settings page), gated SYSTEM.SETTINGS."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.services.security import require_permission

_ADMIN = [Depends(require_permission("SYSTEM.SETTINGS"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["mes"])

    @router.get("/mes/status", dependencies=_ADMIN)
    async def status() -> dict:
        return module.status()

    @router.put("/mes/config", dependencies=_ADMIN)
    async def set_config(body: dict) -> dict:
        return await module.set_config(
            gate_enabled=body.get("gate_enabled"),
            publish_enabled=body.get("publish_enabled"),
        )

    return router

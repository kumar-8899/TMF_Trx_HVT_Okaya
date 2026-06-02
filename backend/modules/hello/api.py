"""The hello router (CORE.md §9): GET /hello/ping."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.services.bridge import BridgeError, BridgeTimeout


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["hello"])

    @router.get("/ping")
    async def ping() -> dict:
        try:
            return await module.ping()
        except BridgeTimeout as exc:
            # External dependency timed out (BRIDGE §5 -> HTTP 502).
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except BridgeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return router

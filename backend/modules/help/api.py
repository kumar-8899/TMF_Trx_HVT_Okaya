"""Help router (prefix /help). HELP.VIEW = user docs (all roles); HELP.DEV = dev
docs (super_admin). Dev inclusion is decided from the caller's permissions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from core.services.auth_verify import Principal, permission_granted
from core.services.security import require_permission

_VIEW = Depends(require_permission("HELP.VIEW"))


def _dev(principal: Principal) -> bool:
    return permission_granted(frozenset(principal.permissions), "HELP.DEV")


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["help"])

    @router.get("/help/index")
    async def index(principal: Principal = _VIEW) -> list[dict]:
        return module.index(include_dev=_dev(principal))

    @router.get("/help/search")
    async def search(q: str = "", principal: Principal = _VIEW) -> list[dict]:
        return module.search(q, include_dev=_dev(principal))

    @router.get("/help/for-route")
    async def for_route(route: str, principal: Principal = _VIEW) -> dict | None:
        return module.for_route(route, include_dev=_dev(principal))

    @router.get("/help/page/{page_id}")
    async def page(page_id: str, principal: Principal = _VIEW) -> dict:
        doc = module.page(page_id, include_dev=_dev(principal))
        if doc is None:
            raise HTTPException(status_code=404, detail=f"no help page '{page_id}'")
        return doc

    @router.get("/help/assets")
    async def assets(principal: Principal = _VIEW) -> list[dict]:
        """Captions + capture version + staleness for every image the caller may see."""
        return module.assets(include_dev=_dev(principal))

    @router.get("/help/asset/{asset_id}")
    async def asset(asset_id: str, principal: Principal = _VIEW) -> Response:
        got = module.asset(asset_id, include_dev=_dev(principal))
        if got is None:
            raise HTTPException(status_code=404, detail=f"no help asset '{asset_id}'")
        body, mime = got
        return Response(content=body, media_type=mime, headers={"Cache-Control": "private, max-age=300"})

    @router.get("/help/app-asset/{name:path}")
    async def app_asset(name: str, principal: Principal = _VIEW) -> Response:
        """An image an app ships with its own manual pages (app/<name>/portal/img/)."""
        got = module.app_asset(name)
        if got is None:
            raise HTTPException(status_code=404, detail=f"no app asset '{name}'")
        body, mime = got
        return Response(content=body, media_type=mime, headers={"Cache-Control": "private, max-age=300"})

    @router.get("/help/facts")
    async def facts(principal: Principal = _VIEW) -> dict:
        """Generated framework facts (tools/gen_devguide.py). Developer-only, source checkout only."""
        doc = module.facts(include_dev=_dev(principal))
        if doc is None:
            raise HTTPException(status_code=404, detail="no generated facts available")
        return doc

    return router

"""Recipe router (RECIPE.md §11). Mounted under /recipes.

R1: step-type introspection. Reads gated on RECIPE.VIEW; authoring (RECIPE.EDIT)
lands in R2. Errors are RFC-7807 via web.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.services.security import require_permission
from modules.recipe.registry import StepTypeError

_VIEW = [Depends(require_permission("RECIPE.VIEW"))]


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["recipe"])

    @router.get("/step-types", dependencies=_VIEW)
    async def step_types() -> list[dict]:
        return module.list_step_types()

    @router.get("/step-types/{type_id}/schema", dependencies=_VIEW)
    async def step_schema(type_id: str) -> dict:
        try:
            return module.get_step_schema(type_id)
        except StepTypeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router

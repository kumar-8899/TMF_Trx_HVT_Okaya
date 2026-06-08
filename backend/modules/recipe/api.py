"""Recipe router (RECIPE.md §11). Mounted under /recipes.

R1: step-type introspection. Reads gated on RECIPE.VIEW; authoring (RECIPE.EDIT)
lands in R2. Errors are RFC-7807 via web.py.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from core.services.security import require_permission
from modules.recipe.registry import StepTypeError
from modules.recipe.storage import RecipeExistsError, RecipeStoreError, RecipeValidationError

_VIEW = [Depends(require_permission("RECIPE.VIEW"))]
_EDIT = [Depends(require_permission("RECIPE.EDIT"))]


async def _guard(coro):
    try:
        return await coro
    except RecipeExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RecipeValidationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc
    except RecipeStoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["recipe"])

    @router.get("/step-types", dependencies=_VIEW)
    async def step_types() -> list[dict]:
        return module.list_step_types()

    @router.get("/step-types/{type_id}/schema", dependencies=_VIEW)
    async def step_schema(type_id: str, resolved: bool = False) -> dict:
        try:
            return module.get_step_schema(type_id, resolved=resolved)
        except StepTypeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # --- discovery (R2) ----------------------------------------------------

    @router.get("", dependencies=_VIEW)
    async def list_recipes(status: str | None = None, tag: str | None = None) -> list[dict]:
        return await module.list_recipes(status=status, tag=tag)

    @router.get("/by-barcode/{barcode}", dependencies=_VIEW)
    async def by_barcode(barcode: str) -> dict:
        return await _guard(module.get_by_barcode(barcode))

    @router.get("/export-all", dependencies=_VIEW)
    async def export_all() -> Response:
        data = await module.export_all()
        return Response(content=data, media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="recipes-all.zip"'})

    @router.post("/import", dependencies=_EDIT)
    async def import_recipes(request: Request, mode: str = "add") -> dict:
        return await _guard(module.import_bundle(await request.body(), mode))

    @router.post("/validate", dependencies=_VIEW)
    async def validate_payload(body: dict, station: str | None = None) -> dict:
        # Validate an arbitrary (draft) payload before publishing.
        return module.validate(body, station=station)

    @router.get("/{recipe_id}", dependencies=_VIEW)
    async def get_recipe(recipe_id: str) -> dict:
        return await _guard(module.get_recipe(recipe_id))

    @router.get("/{recipe_id}/versions", dependencies=_VIEW)
    async def list_versions(recipe_id: str) -> list[dict]:
        return await _guard(module.list_versions(recipe_id))

    @router.get("/{recipe_id}/versions/{n}", dependencies=_VIEW)
    async def get_version(recipe_id: str, n: int) -> dict:
        return await _guard(module.get_recipe(recipe_id, version=n))

    # --- authoring (R2) ----------------------------------------------------

    @router.post("", dependencies=_EDIT, status_code=201)
    async def create_recipe(body: dict) -> dict:
        return await _guard(module.create_recipe(body))

    @router.post("/{recipe_id}/drafts", dependencies=_EDIT, status_code=201)
    async def fork_draft(recipe_id: str) -> dict:
        return await _guard(module.fork_draft(recipe_id))

    @router.put("/{recipe_id}/drafts/{draft_id}", dependencies=_EDIT)
    async def save_draft(recipe_id: str, draft_id: str, body: dict) -> dict:
        return await _guard(module.save_draft(recipe_id, draft_id, body))

    @router.post("/{recipe_id}/drafts/{draft_id}/publish", dependencies=_EDIT)
    async def publish_draft(recipe_id: str, draft_id: str) -> dict:
        return await _guard(module.publish_draft(recipe_id, draft_id))

    @router.post("/{recipe_id}/deprecate", dependencies=_EDIT)
    async def deprecate(recipe_id: str, body: dict | None = None) -> dict:
        return await _guard(module.deprecate(recipe_id, (body or {}).get("reason", "")))

    @router.post("/{recipe_id}/versions/{n}/archive", dependencies=_EDIT)
    async def archive(recipe_id: str, n: int) -> dict:
        return await _guard(module.archive(recipe_id, n))

    @router.post("/{recipe_id}/versions/{n}/validate", dependencies=_VIEW)
    async def validate(recipe_id: str, n: int, station: str | None = None) -> dict:
        recipe = await _guard(module.get_recipe(recipe_id, version=n))
        return module.validate(recipe, station=station)

    @router.get("/{recipe_id}/export", dependencies=_VIEW)
    async def export_recipe(recipe_id: str, versions: str = "latest") -> Response:
        data = await _guard(module.export_recipe(recipe_id, versions))
        return Response(content=data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="recipe-{recipe_id}.zip"'})

    @router.get("/{recipe_id}/diff", dependencies=_VIEW)
    async def diff(recipe_id: str, from_: int = Query(..., alias="from"), to: int = 0) -> dict:
        return await _guard(module.diff(recipe_id, from_, to))

    return router

"""Recipe contract (RECIPE.md §11). Siblings resolve via core.get_contract("recipe").

R1 implements the step-type introspection surface; authoring/validation/diff/
export-import methods land in later slices (R2-R6).
"""

from __future__ import annotations

from typing import Protocol


class RecipeContract(Protocol):
    # step-type registry introspection (R1)
    def list_step_types(self) -> list[dict]: ...
    def get_step_schema(self, type_id: str) -> dict: ...

    # discovery (R2)
    async def list_recipes(self, status: str | None = None, tag: str | None = None) -> list[dict]: ...
    async def get_recipe(self, recipe_id: str, version: int | None = None) -> dict: ...

    # authoring (R2)
    async def create_recipe(self, payload: dict) -> dict: ...
    async def publish_draft(self, recipe_id: str, draft_id: str) -> dict: ...

    # validation (R3)
    async def validate(self, payload: dict, station: int | None = None, strict: bool = False) -> dict: ...

    # execution wire (R4)
    async def fetch(self, recipe_id: str, version: int | None, run_parameters: dict | None) -> dict: ...

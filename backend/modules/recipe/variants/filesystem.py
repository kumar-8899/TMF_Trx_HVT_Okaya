"""Recipe `filesystem` variant (RECIPE.md §12).

R1: discovers step types, builds the schema set, serves step-type introspection.
Authoring/versioning (R2), validation (R3), execution wire (R4), export/import
(R5), and diff (R6) extend this variant in later slices.
"""

from __future__ import annotations

from pathlib import Path

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.recipe import registry as step_registry
from modules.recipe.api import build_router
from modules.recipe.validation.schema import SchemaSet


class FilesystemRecipe:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.station = core.station
        self.root = Path(config.get("root", "data/recipes"))
        self._schemas: SchemaSet | None = None
        self.router = build_router(self)
        self.mqtt_handlers: list = []

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "FilesystemRecipe":
        return cls(core, config)

    async def init(self) -> None:
        step_registry.discover_step_types()  # populate the step-type registry
        self._schemas = SchemaSet()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        n = len(step_registry.all_types())
        return Health(status=HealthStatus.OK, detail=f"{n} step types")

    # --- step-type introspection (R1) --------------------------------------

    def list_step_types(self) -> list[dict]:
        return [
            {
                "type_id": rec.type_id,
                "display_name": rec.display_name,
                "composite": rec.composite,
                "capabilities": list(rec.capabilities),
            }
            for rec in step_registry.all_types().values()
        ]

    def get_step_schema(self, type_id: str) -> dict:
        return step_registry.get(type_id).schema

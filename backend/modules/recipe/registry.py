"""Step-type registry (RECIPE.md §4) — plugins registered like drivers.

A module-internal registry (distinct from the core module registry). New step
type = a dir under step_types/ with schema.json + type.py carrying
@register_step_type. Autodiscovery imports each type.py; schemas load by dir.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from dataclasses import dataclass
from pathlib import Path


class StepTypeError(Exception):
    """Duplicate registration or lookup of an unknown step type."""


@dataclass
class StepTypeRecord:
    type_id: str
    display_name: str
    composite: bool
    capabilities: tuple[str, ...]
    schema_path: str
    dir: Path
    schema: dict | None = None


_REGISTRY: dict[str, StepTypeRecord] = {}


def register_step_type(
    type_id: str,
    display_name: str = "",
    schema_path: str = "schema.json",
    composite: bool = False,
    capabilities: tuple[str, ...] = (),
):
    def deco(cls):
        if type_id in _REGISTRY:
            raise StepTypeError(f"duplicate step type '{type_id}'")
        _REGISTRY[type_id] = StepTypeRecord(
            type_id=type_id,
            display_name=display_name or type_id,
            composite=bool(composite),
            capabilities=tuple(capabilities),
            schema_path=schema_path,
            dir=Path(inspect.getfile(cls)).parent,
        )
        return cls

    return deco


def discover_step_types() -> list[str]:
    """Import every step_types/<type>/type.py so the decorators fire; load schemas."""
    import modules.recipe.step_types as pkg

    found: list[str] = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.ispkg and not info.name.startswith("_"):
            importlib.import_module(f"modules.recipe.step_types.{info.name}.type")
            found.append(info.name)
    for rec in _REGISTRY.values():
        if rec.schema is None:
            rec.schema = json.loads((rec.dir / rec.schema_path).read_text(encoding="utf-8"))
    return found


def get(type_id: str) -> StepTypeRecord:
    rec = _REGISTRY.get(type_id)
    if rec is None:
        raise StepTypeError(f"unknown step type '{type_id}'")
    return rec


def all_types() -> dict[str, StepTypeRecord]:
    return dict(_REGISTRY)


def clear() -> None:
    _REGISTRY.clear()

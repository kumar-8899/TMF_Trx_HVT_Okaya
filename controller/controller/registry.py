"""Step-type registry (PYTHON_CONTROLLER.md §7.1, §7.6).

A step type = param schema + required bindings + handler, registered by decorator. A
type not in the registry does not exist; a recipe referencing one fails validation.
`sequencer.list_test_classes` returns this, each flagged primitive|application, so the
authoring UI needs no change."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StepType:
    type_id: str
    handler_cls: type
    display_name: str
    composite: bool
    kind: str                          # "primitive" | "application"
    required_signals: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    schema_path: str | None = None


STEP_REGISTRY: dict[str, StepType] = {}


def register_step_type(*, type_id: str, display_name: str = "", composite: bool = False,
                       kind: str = "application", required_signals: tuple = (),
                       required_actions: tuple = (), schema_path: str | None = None):
    def deco(cls):
        if type_id in STEP_REGISTRY:
            raise ValueError(f"duplicate step type '{type_id}'")
        STEP_REGISTRY[type_id] = StepType(
            type_id=type_id, handler_cls=cls, display_name=display_name or type_id,
            composite=composite, kind=kind, required_signals=tuple(required_signals),
            required_actions=tuple(required_actions), schema_path=schema_path)
        return cls
    return deco


def get(type_id: str) -> StepType | None:
    return STEP_REGISTRY.get(type_id)


def list_test_classes() -> list[dict]:
    return [{"type_id": t.type_id, "display_name": t.display_name, "composite": t.composite,
             "kind": t.kind, "required_signals": list(t.required_signals),
             "required_actions": list(t.required_actions)}
            for t in sorted(STEP_REGISTRY.values(), key=lambda t: t.type_id)]


def _schema_for(t: StepType) -> dict | None:
    """Resolve a step type's JSON schema: `schema_path` relative to the handler's dir
    (app steps ship `schema.json` beside handler.py), else the core convention
    `schemas/<type_id>.json` beside core.py. None if absent/unreadable."""
    handler_dir = Path(inspect.getfile(t.handler_cls)).parent
    rel = t.schema_path or f"schemas/{t.type_id}.json"
    p = handler_dir / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a bad schema file must not crash the catalog
        return None


def catalog() -> list[dict]:
    """The full step-type catalog for authoring + validation: each type's metadata plus its
    resolved JSON schema (the parameter contract). This is the single source of truth the
    recipe module consumes to author/validate controller-native recipes (§7.6)."""
    return [{"type_id": t.type_id, "display_name": t.display_name, "composite": t.composite,
             "kind": t.kind, "required_signals": list(t.required_signals),
             "required_actions": list(t.required_actions), "schema": _schema_for(t)}
            for t in sorted(STEP_REGISTRY.values(), key=lambda t: t.type_id)]

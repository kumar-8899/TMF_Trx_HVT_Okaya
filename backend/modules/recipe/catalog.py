"""Controller step-type catalog for the recipe module (recipe-unify P2).

Controller-native recipes use `{id, type, params:{steps:[...]}}` and the controller's step
types (the 8 core + the app's `step_type_packages`) — a different registry + envelope from the
recipe module's legacy 16 step types. Rather than duplicate, the recipe module reads the
**controller's** catalog (registry.catalog(), P1) as the single source of truth for authoring
and validating controller-native recipes.

The controller package is a sibling of backend/ in every framework checkout; we add it to
sys.path and import it (backend→controller is fine; the one-directional rule is that the
*controller* imports nothing from backend). If the controller isn't importable, the legacy
recipe path is unaffected — controller-native validation just reports the catalog is missing.
"""

from __future__ import annotations

import sys
from functools import lru_cache

from jsonschema import Draft7Validator

from core.paths import bundle_root

_REPO = bundle_root()      # source: repo root; frozen: run.dist (core/paths.py, not __file__)
_CONTROLLER = _REPO / "controller"


def is_controller_native(recipe: dict) -> bool:
    """A controller-native recipe's steps carry `type` (not the legacy `step_type`)."""
    steps = recipe.get("steps") or []
    return bool(steps) and any(("type" in s and "step_type" not in s) for s in steps if isinstance(s, dict))


@lru_cache(maxsize=8)
def _load(step_type_paths: tuple, step_type_packages: tuple) -> tuple[dict, str | None]:
    if _CONTROLLER.exists() and str(_CONTROLLER) not in sys.path:
        sys.path.insert(0, str(_CONTROLLER))
    try:
        import controller.step_types  # noqa: F401 — registers the 8 core types
        from controller import registry as creg
        from controller.packages import load_step_type_packages
        load_step_type_packages(list(step_type_paths), list(step_type_packages))
        return {c["type_id"]: c for c in creg.catalog()}, None
    except Exception as exc:  # noqa: BLE001 — no controller → legacy path stays intact
        return {}, str(exc)


def build_catalog(step_type_paths=None, step_type_packages=None) -> tuple[dict, str | None]:
    """{type_id: {schema, composite, required_signals, required_actions, kind}}, error."""
    return _load(tuple(step_type_paths or ()), tuple(step_type_packages or ()))


def validate_controller_recipe(recipe: dict, catalog: dict) -> list[str]:
    """Every step type is in the catalog; its params satisfy the type's JSON schema; composites
    recurse into params.steps. Signal/action *existence* is a station-specific dry-run concern
    (controller §12.2), not recipe-authoring validation, so it is not checked here."""
    errors: list[str] = []

    def walk(steps, path):
        for i, step in enumerate(steps or []):
            sid = step.get("id") or f"{path}[{i}]"
            t = step.get("type")
            entry = catalog.get(t)
            if entry is None:
                errors.append(f"{sid}: unknown step type '{t}'")
                continue
            schema = entry.get("schema")
            params = step.get("params") or {}
            if schema:
                for e in sorted(Draft7Validator(schema).iter_errors(params), key=lambda e: e.path):
                    loc = ".".join(str(p) for p in e.path) or "params"
                    errors.append(f"{sid}.{loc}: {e.message}")
            if entry.get("composite"):
                walk(params.get("steps"), sid)

    walk(recipe.get("steps"), "root")
    return errors

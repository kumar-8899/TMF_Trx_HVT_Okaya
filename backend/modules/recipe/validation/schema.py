"""Schema validation (RECIPE.md §7, STEP_TYPES §0).

Builds a referencing Registry from the _common schemas + every registered step
type's params schema, so $ref resolution works. validate_step does the two-pass
check (envelope, then type-specific params). Recursive recipe-tree validation
lands in R3 on top of this.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from modules.recipe import registry as step_registry

_ENVELOPE_REF = {"$ref": "tmf:recipe:_common/envelope"}


def _common_dir() -> Path:
    import modules.recipe.step_types as pkg

    return Path(pkg.__file__).parent / "_common"


class SchemaSet:
    def __init__(self) -> None:
        resources = []
        for path in sorted(_common_dir().glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            resources.append((schema["$id"], DRAFT202012.create_resource(schema)))
        for rec in step_registry.all_types().values():
            resources.append((rec.schema["$id"], DRAFT202012.create_resource(rec.schema)))
        self.registry = Registry().with_resources(resources)
        self._envelope = Draft202012Validator(_ENVELOPE_REF, registry=self.registry)
        self._params = {
            tid: Draft202012Validator(rec.schema, registry=self.registry)
            for tid, rec in step_registry.all_types().items()
        }

    def validate_step(self, step: dict) -> list[str]:
        """Return a list of human-readable errors ([] = valid)."""
        errors = [f"{e.json_path}: {e.message}" for e in self._envelope.iter_errors(step)]
        type_id = step.get("step_type")
        if type_id not in self._params:
            errors.append(f"unknown step_type '{type_id}'")
        else:
            errors += [
                f"params{e.json_path[1:]}: {e.message}"
                for e in self._params[type_id].iter_errors(step.get("params", {}))
            ]
        return errors

    def validate_recipe(self, recipe: dict) -> list[str]:
        """Recursive schema pass over the whole step tree + duplicate step_id check."""
        errors: list[str] = []
        seen: set[str] = set()

        def walk(steps, path: str) -> None:
            for i, step in enumerate(steps or []):
                loc = f"{path}[{i}]"
                errors.extend(f"{loc} {e}" for e in self.validate_step(step))
                sid = step.get("step_id")
                if sid and sid in seen:
                    errors.append(f"{loc} duplicate step_id '{sid}'")
                elif sid:
                    seen.add(sid)
                params = step.get("params", {}) or {}
                for key in ("inner_steps", "then_steps", "else_steps"):
                    if isinstance(params.get(key), list):
                        walk(params[key], f"{loc}.{key}")

        for section in ("setup_steps", "steps", "teardown_steps"):
            walk(recipe.get(section), section)
        return errors

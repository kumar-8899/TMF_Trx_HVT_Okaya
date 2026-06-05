"""Semantic validation (RECIPE.md §7) — self-contained logical checks.

Runs only after the schema pass (assumes well-shaped steps). Cross-reference
checks (variables/instances/test-classes) are separate and deferred.
"""

from __future__ import annotations

_SECTIONS = ("setup_steps", "steps", "teardown_steps")
_INNER_KEYS = ("inner_steps", "then_steps", "else_steps")


def check_semantic(recipe: dict) -> list[str]:
    errors: list[str] = []
    seen_measures: set[str] = set()

    def walk(steps: list | None) -> None:
        for step in steps or []:
            stype = step.get("step_type")
            sid = step.get("step_id", "?")
            p = step.get("params", {}) or {}

            if stype == "measure":
                seen_measures.add(p.get("store_as") or sid)

            elif stype == "compare":
                src = p.get("source", {}) or {}
                ref = src.get("measurement")
                if ref is not None and ref not in seen_measures:
                    errors.append(f"{sid}: compare references unknown measurement '{ref}'")

            elif stype == "sweep":
                rng = p.get("range")
                if rng and rng.get("end") < rng.get("start"):
                    errors.append(f"{sid}: sweep range end < start (step is positive; empty sweep)")

            elif stype == "ramp_until":
                if p.get("end") is not None and p.get("start") is not None and p["end"] < p["start"]:
                    errors.append(f"{sid}: ramp_until end < start (step_size is positive; unreachable)")

            for key in _INNER_KEYS:
                if isinstance(p.get(key), list):
                    walk(p[key])

    for section in _SECTIONS:
        walk(recipe.get(section))
    return errors

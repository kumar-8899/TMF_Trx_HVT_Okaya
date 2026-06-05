"""Cross-reference validation (RECIPE.md §7) — DEFERRED, warn-only.

Confirming variables exist (Variable Engine), instances exist (Instance Registry),
and test_class_ids are registered (`bridge.request("sequencer.list_test_classes")`)
needs subsystems that don't exist yet. Until then this collects the references a
recipe makes and returns a single non-blocking warning, so old/new recipes are
never rejected on a check we cannot yet perform.
"""

from __future__ import annotations

_SECTIONS = ("setup_steps", "steps", "teardown_steps")
_INNER_KEYS = ("inner_steps", "then_steps", "else_steps")
_VAR_PARAM_KEYS = ("variable",)


def _collect(recipe: dict) -> tuple[set[str], set[str]]:
    variables: set[str] = set()
    test_classes: set[str] = set()

    def cond_var(cond: dict | None) -> None:
        if isinstance(cond, dict) and cond.get("variable"):
            variables.add(cond["variable"])

    def walk(steps: list | None) -> None:
        for step in steps or []:
            p = step.get("params", {}) or {}
            for k in _VAR_PARAM_KEYS:
                if isinstance(p.get(k), str):
                    variables.add(p[k])
            src = p.get("source")
            if isinstance(src, dict) and src.get("variable"):
                variables.add(src["variable"])
            cond_var(p.get("until"))
            cond_var(p.get("condition"))
            if step.get("step_type") == "test_reference" and p.get("test_class_id"):
                test_classes.add(p["test_class_id"])
            for key in _INNER_KEYS:
                if isinstance(p.get(key), list):
                    walk(p[key])

    for section in _SECTIONS:
        walk(recipe.get(section))
    return variables, test_classes


def check_cross_references(recipe: dict) -> list[str]:
    """Returns warnings (never errors) while the check is deferred."""
    variables, test_classes = _collect(recipe)
    if not variables and not test_classes:
        return []
    return [
        f"cross-reference deferred: {len(variables)} variable ref(s) + "
        f"{len(test_classes)} test_class ref(s) unverified "
        "(Variable Engine / sequencer.list_test_classes not available yet)"
    ]

"""Structured version diff (RECIPE.md §5.5).

Flattens both step trees by step_id, reports added/removed/modified steps and
changed header fields. Powers GET /recipes/{id}/diff and the save summary.
"""

from __future__ import annotations

_SECTIONS = ("setup_steps", "steps", "teardown_steps")
_INNER_KEYS = ("inner_steps", "then_steps", "else_steps")
_HEADER_FIELDS = (
    "name", "description", "owner", "tags", "required_role",
    "estimated_duration_s", "barcode_prefixes", "run_parameters", "defaults",
)


def _flatten(recipe: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}

    def walk(steps: list | None) -> None:
        for step in steps or []:
            sid = step.get("step_id")
            if sid:
                out[sid] = step
            p = step.get("params", {}) or {}
            for key in _INNER_KEYS:
                if isinstance(p.get(key), list):
                    walk(p[key])

    for section in _SECTIONS:
        walk(recipe.get(section))
    return out


def diff_recipes(old: dict, new: dict) -> dict:
    o, n = _flatten(old), _flatten(new)
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    modified = sorted(sid for sid in (set(o) & set(n)) if o[sid] != n[sid])
    header = {
        f: {"from": old.get(f), "to": new.get(f)}
        for f in _HEADER_FIELDS
        if old.get(f) != new.get(f)
    }
    return {
        "steps_added": added,
        "steps_removed": removed,
        "steps_modified": modified,
        "header_changes": header,
    }


def diff_summary(diff: dict, version: int, name: str) -> str:
    return (
        f"Saved v{version} of '{name}' "
        f"({len(diff['steps_added'])} added, {len(diff['steps_removed'])} removed, "
        f"{len(diff['steps_modified'])} modified)"
    )

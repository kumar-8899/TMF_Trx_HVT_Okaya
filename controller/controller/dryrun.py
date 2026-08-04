"""Dry run (PYTHON_CONTROLLER.md §12.2).

`run.start {"dry_run": true}` fetches + validates the recipe, walks the ENTIRE step tree,
resolves every signal and action name against the calling station's map, and checks each
step type is registered and its declared `required_signals` / `required_actions` are
satisfied — touching NO hardware and running NO handler body. It catches a missing variable
at step 12 before an operator does. The result is DRY_RUN_PASS or DRY_RUN_FAIL with every
error listed (not just the first — a dry run should surface all config gaps in one pass)."""

from __future__ import annotations

from controller import registry


def dry_run(recipe: dict, variables) -> tuple[str, list[str]]:
    signals = set(getattr(variables, "signals", {}) or {})
    actions = set(getattr(variables, "actions", {}) or {})
    errors: list[str] = []

    def _check_names(sid, want_signals, want_actions):
        for name in want_signals:
            if name and name not in signals:
                errors.append(f"{sid}: signal '{name}' not in station map")
        for name in want_actions:
            if name and name not in actions:
                errors.append(f"{sid}: action '{name}' not in station map")

    def walk(steps, path):
        for i, step in enumerate(steps or []):
            sid = step.get("id") or f"{path}[{i}]"
            t = step.get("type")
            st = registry.get(t)
            if st is None:
                errors.append(f"{sid}: unknown step type '{t}'")
                continue
            params = step.get("params") or {}
            # declared required bindings (§7.1)
            _check_names(sid, st.required_signals, st.required_actions)
            # param-referenced names, when the handler declares how to find them
            fn = getattr(st.handler_cls, "bindings", None)
            if callable(fn):
                try:
                    ref = fn(params) or {}
                except Exception as exc:  # noqa: BLE001 — a broken params shape is a dry-run failure
                    errors.append(f"{sid}: bad params for '{t}': {exc}")
                    ref = {}
                _check_names(sid, ref.get("signals", []), ref.get("actions", []))
            if st.composite:
                walk(params.get("steps"), sid)

    walk(recipe.get("steps"), "root")
    return ("DRY_RUN_PASS" if not errors else "DRY_RUN_FAIL"), errors

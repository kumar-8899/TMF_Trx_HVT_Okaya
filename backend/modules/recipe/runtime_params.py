"""`${run.x}` substitution (RECIPE.md §8) — pure substitution, no expression lang.

Whole-string `${run.<name>}` is replaced by the typed run-parameter value
(matches _common/value_ref). Applied at run start, before the recipe goes to
LabVIEW.
"""

from __future__ import annotations

import re

_RUN_REF = re.compile(r"^\$\{run\.([a-z_][a-z0-9_]*)\}$")


def substitute(obj, params: dict):
    if isinstance(obj, str):
        m = _RUN_REF.match(obj)
        if m and m.group(1) in params:
            return params[m.group(1)]  # typed value, not a string
        return obj
    if isinstance(obj, dict):
        return {k: substitute(v, params) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, params) for v in obj]
    return obj

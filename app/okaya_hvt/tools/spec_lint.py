#!/usr/bin/env python
"""spec-lint for the Okaya HVT app — the test-spec drift gate (docs/TEST_SPECS.md).

Cross-checks every `specs/<test>.md` against the code + recipe:
  - measurements listed in a spec == what the step group actually emits in a sim run;
  - signals/actions listed == what the group's steps touch (core reads + app required_*);
  - parameters (authored specs) == the step type's schema.json properties.

    python app/okaya_hvt/tools/spec_lint.py <recipe.json>

Exit 0 = all specs in sync, 1 = drift (errors). Warnings never fail the gate. No default
recipe — the sequence is not yet authored (cloned from okaya_transformer without one).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
FORK_ROOT = APP_DIR.parents[1]
CONTROLLER_DIR = FORK_ROOT / "controller"
for _p in (str(CONTROLLER_DIR), str(FORK_ROOT), str(APP_DIR), str(APP_DIR / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import controller.step_types  # noqa: E402,F401 — register core types
import instrument_libs  # noqa: E402,F401
import okaya_hvt_steps  # noqa: E402,F401 — register app step types
from controller import registry  # noqa: E402
from controller import speclint  # noqa: E402

import run_sim  # noqa: E402 — reuse the same in-process sim to learn emitted measurements


def main(recipe_path: str) -> int:
    rp = Path(recipe_path)
    recipe = json.loads(rp.read_text(encoding="utf-8"))
    varmap = json.loads((APP_DIR / "maps" / "st1.json").read_text(encoding="utf-8"))
    map_signals = set(varmap.get("signals", {}))

    # emitted measurements per step id, from a real sim run of this recipe
    _verdict, rows = run_sim.simulate(rp)
    emitted_by_step: dict[str, list[str]] = {}
    for r in rows:
        emitted_by_step.setdefault(r["step_id"], []).append(r["name"])

    report = speclint.check_specs(APP_DIR / "specs", recipe, registry.catalog(),
                                  emitted_by_step, map_signals)
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: spec_lint.py <recipe.json>  (no default — the sequence is not yet authored)")
    raise SystemExit(main(sys.argv[1]))

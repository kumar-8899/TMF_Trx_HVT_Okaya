"""In-process simulation runner: no broker, no hardware, no UI.

TEMPLATE for an app's `app/<slug>/tools/run_sim.py` (new-test-app, Phase 4). Copy it, then edit
ONLY the two marked blocks: INSTRUMENTS and NEGATIVE_CASES. The rest is the verified harness.

    python app/<slug>/tools/run_sim.py [recipe.json]

Why it looks like this (each line was learned the hard way):
  * The instruments must be CONNECTED (`loop.run(reg.connect_all())`) before the sequencer
    runs. Without it every read/write fails inside the step, no measurement is emitted and the
    run ends with a silent empty verdict, which looks like a broken recipe but is not.
  * Instrument ids here must equal the `instance` names in `maps/<station>.json`; they are the
    same records an operator creates later on Config -> Instruments.
  * A negative case changes what the SIM transport answers, then expects FAIL. Sim answers are
    fixed canned values (see each driver's `_SIM` table), so a PASS run only passes when the
    spec limits contain those values.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]          # app/<slug>
REPO_ROOT = APP_DIR.parents[1]                         # fork root (holds instrument_libs/)
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "controller"))

from controller.step_types import core  # noqa: E402,F401  (import registers the core step types)
import instrument_libs  # noqa: E402,F401                   (import registers the driver libraries)
# App step types (if any), e.g.:  import <slug>_steps  # noqa: F401  (sys.path needs app/<slug>)

from controller.instruments.registry import InstrumentRegistry  # noqa: E402
from controller.instruments.variables import StationVariables, load_variable_map  # noqa: E402
from controller.loop import AsyncLoopThread  # noqa: E402
from controller.results import FAIL, PASS  # noqa: E402,F401  (FAIL is for NEGATIVE_CASES)
from controller.sequencer import Sequencer  # noqa: E402

STATION = "st1"
MAP_PATH = APP_DIR / "maps" / f"{STATION}.json"

# ---- EDIT 1: the instrument records (id = the map's `instance`, simulated, params from the driver) ----
INSTRUMENTS = [
    # {"id": "psu", "library": "keysight_e36xx", "stations": [STATION], "simulated": True,
    #  "params": {"resource": "SIM"}},
]

# ---- EDIT 2: negative cases: (title, patch(reg), expected verdict). Prove the limits can FAIL. ----
#   def _low_supply(reg):
#       reg.require("psu").transport.responses["MEAS:VOLT?"] = "4.8000"
NEGATIVE_CASES: list[tuple[str, object, str]] = [
    # ("supply voltage low", _low_supply, FAIL),
]


def run_recipe(recipe: dict, patch=None) -> str:
    """Run `recipe` once in-process, print every measurement, return the verdict."""
    loop = AsyncLoopThread()
    loop.start()
    try:
        reg = InstrumentRegistry(loop)
        reg.build(INSTRUMENTS, simulation=True)
        for skipped in reg.skipped:
            print(f"  WARNING: skipped {skipped['id']}: {skipped['reason']}")
        loop.run(reg.connect_all())                    # REQUIRED: see the module docstring
        if patch:
            patch(reg)
        variables = StationVariables(STATION, load_variable_map(MAP_PATH), reg, loop)

        def emit(event_type: str, payload: dict) -> None:
            if event_type == "test-result":
                unit = payload.get("unit") or ""
                print(f"    {payload.get('step_id', '?')}.{payload.get('name', '?')}: "
                      f"{payload.get('measured')} {unit} [{payload.get('expected', '')}] -> "
                      f"{payload.get('result', '?')}")

        seq = Sequencer(variables, emit, lambda lvl, msg, **_: None)
        return seq.run(recipe, run_id="sim", station=STATION, run_parameters={},
                       deadline_ts=float("inf"), aborted_fn=lambda: False)
    finally:
        loop.stop()


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted((APP_DIR / "recipes").glob("*.json"))[0]
    recipe = json.loads(path.read_text(encoding="utf-8"))
    if not INSTRUMENTS:
        print("run_sim: INSTRUMENTS is empty: fill in the instrument records (EDIT 1).")
        return 2

    print(f"=== {path.name}: default simulation ===")
    verdict = run_recipe(recipe)
    print(f"VERDICT: {verdict}")
    ok = verdict == PASS
    for title, patch, expected in NEGATIVE_CASES:
        print(f"\n=== negative case: {title} (expect {expected}) ===")
        got = run_recipe(recipe, patch)
        print(f"VERDICT: {got}")
        ok = ok and got == expected
    if not NEGATIVE_CASES:
        print("\nrun_sim: no negative case defined (EDIT 2): a PASS alone proves nothing.")
        ok = False
    print("\nAll sim assertions passed." if ok else "\nrun_sim: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""In-process simulation runner for the Okaya HVT Testbench.

Loads the self-contained instrument drivers + the app step-type package + the station
variable map, builds every instrument in SIMULATION, and drives the controller Sequencer
over the recipe — printing each measurement and the final verdict. No broker, no MQTT, no
hardware, no Instruments-page config (instances are declared here for the in-process run).

    python app/okaya_hvt/tools/run_sim.py <recipe.json>

Exit code 0 = PASS, 1 = FAIL — so it doubles as a fast CI proof.

Cloned from okaya_transformer's run_sim.py (TMF_Trx_Functional_Oakay): the `ni` instrument
(and its sim_couple wiring for the old variac_regulate step) is REMOVED — this bench
excludes NI entirely. There is no default recipe yet (the old transformer_functional.json
was Variac-based end to end and did not carry over) — always pass a recipe path until the
new sequence is authored (add-bench-test)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]        # app/okaya_hvt
FORK_ROOT = APP_DIR.parents[1]                       # repo root (holds instrument_libs/)
CONTROLLER_DIR = FORK_ROOT / "controller"            # the controller package repo

# Resolve imports the way the real controller does: controller package, the fork root
# (self-contained instrument_libs), and this app payload (okaya_hvt_steps).
for _p in (str(CONTROLLER_DIR), str(FORK_ROOT), str(APP_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import controller.step_types  # noqa: E402,F401 — registers the 8 core step types
import instrument_libs  # noqa: E402,F401 — registers the bench drivers
import okaya_hvt_steps  # noqa: E402,F401 — registers mux_measure + hipot_acw
from controller.instruments.registry import InstrumentRegistry  # noqa: E402
from controller.instruments.variables import StationVariables  # noqa: E402
from controller.loop import AsyncLoopThread  # noqa: E402
from controller.sequencer import Sequencer  # noqa: E402

# The instrument instances (what the Instruments page provides in the running app). ids MUST
# match the variable map's `instance` names. All simulated for the headless run. No `ni` here
# — this bench excludes the NI instrument entirely (see maps/st1.json).
#
# Two physically separate 8-channel Waveshare relay cards (2026-09, confirmed): relay1 is the
# original card (muxing/IO/hipot routes, channels 0-7 all used), relay2 is a second card for the
# tower-light stack (Red/Green/Buzzer on channels 0-2; this bench has no Yellow tower light).
# `unit_id` here is only a placeholder to keep the two instances distinct — InstrumentRegistry
# treats identical {library, params} as the SAME physical resource and refuses a second instance
# id for it (registry.py `_resource_key`); the real host/port/unit_id (which must differ once
# known) are still unconfirmed for both cards.
INSTRUMENTS = [
    {"id": "relay1", "library": "waveshare_modbus_relay", "stations": ["st1"], "simulated": True,
     "params": {"num_channels": 8, "unit_id": 1}},
    {"id": "relay2", "library": "waveshare_modbus_relay", "stations": ["st1"], "simulated": True,
     "params": {"num_channels": 8, "unit_id": 2}},
    {"id": "meco", "library": "meco_smp72", "stations": ["st1"], "simulated": True, "params": {}},
    {"id": "hipot", "library": "ut5320r", "stations": ["st1"], "simulated": True, "params": {}},
]


def simulate(recipe_path: str | Path, *, on_row=None) -> tuple[str, list[dict]]:
    """Build every instrument in sim, drive the Sequencer over the recipe, and return
    (verdict, rows) where each row is a `test-result` event payload. `on_row(payload)` is
    called for each measurement as it lands (used for live printing). No printing here."""
    recipe = json.loads(Path(recipe_path).read_text(encoding="utf-8"))
    varmap = json.loads((APP_DIR / "maps" / "st1.json").read_text(encoding="utf-8"))

    loop = AsyncLoopThread()
    loop.start()
    reg = InstrumentRegistry(loop)
    rows: list[dict] = []
    try:
        reg.build(INSTRUMENTS, simulation=True)
        loop.run(reg.connect_all())
        variables = StationVariables("st1", varmap, reg, loop)

        def emit(etype: str, payload: dict) -> None:
            if etype == "test-result":
                rows.append(payload)
                if on_row is not None:
                    on_row(payload)

        seq = Sequencer(variables, emit, lambda *a, **k: None)
        verdict = seq.run(recipe, run_id="sim", station="st1", run_parameters={},
                          deadline_ts=time.monotonic() + 120.0, aborted_fn=lambda: False)
        return verdict, rows
    finally:
        try:
            loop.run(reg.disconnect_all())
        except Exception:  # noqa: BLE001
            pass
        loop.stop()


def _print_row(payload: dict) -> None:
    mark = {"PASS": "PASS", "FAIL": "FAIL"}.get(payload.get("result"), "info")
    val = payload.get("measured")
    val_s = f"{val:.4g}" if isinstance(val, (int, float)) else str(val)
    print(f"    [{mark}] {payload.get('name'):26} = {val_s:>10} {payload.get('unit') or '':<3} "
          f" expect[{payload.get('expected') or ''}]")


def run(recipe_path: str | Path) -> int:
    rp = Path(recipe_path)
    recipe = json.loads(rp.read_text(encoding="utf-8"))
    print(f"\nRecipe: {recipe.get('name', recipe.get('recipe_id'))}")
    print("-" * 68)
    verdict, rows = simulate(rp, on_row=_print_row)
    fails = [r for r in rows if r.get("result") == "FAIL"]
    print("-" * 68)
    print(f"measurements: {len(rows)}   failures: {len(fails)}")
    print(f"VERDICT: {verdict}\n")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_sim.py <recipe.json>  (no default — the sequence is not yet authored)")
    raise SystemExit(run(sys.argv[1]))

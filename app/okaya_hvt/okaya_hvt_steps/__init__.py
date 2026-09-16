"""okaya_hvt_steps — application step-type package for the Okaya HVT Testbench
(PYTHON_CONTROLLER.md §7.5). Importing it fires the @register_step_type decorators so the
step types join the controller registry, exactly like a standard package.

  - mux_measure     : energise a set of multiplexing relays (a "route"), settle, read a
                      signal, compare to limits, then always open the route again.
  - hipot_acw       : same routing pattern, but invokes the UT5320R+ hipot tester's
                      `measure_acw` (safety_tester action, non-scalar) instead of reading a
                      scalar signal — leakage current (mA) + a breakdown flag, both judged.

Everything else (fixed set-output, wait, plain measure-and-compare, grouping) uses the
core step types — no code.

Cloned from okaya_transformer_steps (TMF_Trx_Functional_Oakay); that app's second
product-specific type, `variac_regulate` (closed-loop motorised-Variac control via NI
DO/AI), is NOT carried over — this bench excludes the NI instrument entirely. Add app step
types here as the new test sequence is authored (test-step-authoring skill).
"""

from okaya_hvt_steps import hipot_acw  # noqa: F401 — import registers the step type
from okaya_hvt_steps import mux_measure  # noqa: F401 — import registers the step type

__all__ = ["hipot_acw", "mux_measure"]

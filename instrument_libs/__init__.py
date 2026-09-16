"""Self-contained instrument-driver package for the Okaya HVT Testbench (app-owned,
TEMPLATE.md §1.2 — the fork copies in only the drivers it uses and never references the
central Instrument_Library at runtime).

Importing this package fires every driver's registration decorator (§10: "import tree;
decorators fire; duplicate library_id -> fail loudly"). Drivers on this bench:
  - waveshare_modbus_relay (digital_output) — one driver, two 8ch instances (2026-09): `relay1`
                                               (measurement muxing + I/O + hipot routes) and
                                               `relay2` (tower-light stack: Red/Green/Buzzer —
                                               no Yellow on this bench)
  - meco_smp72          (power_meter)    — small feedback-winding RMS voltage
  - itech_it7300        (power_source)   — ITECH IT7322 programmable AC source (VISA)
  - ut5320r             (safety_tester)  — UNI-T UT5320R+ hipot/insulation tester (VISA)

`selec_mfm384` (the AC meter that previously covered input/winding voltage + frequency) was
removed 2026-09 — this bench does not use it. If a general AC meter is needed again later,
author a fresh driver rather than reviving this one from history.
"""

from instrument_libs import digital_output  # noqa: F401
from instrument_libs import power_meter  # noqa: F401
from instrument_libs import power_source  # noqa: F401
from instrument_libs import safety_tester  # noqa: F401

__all__ = ["digital_output", "power_meter", "power_source", "safety_tester"]

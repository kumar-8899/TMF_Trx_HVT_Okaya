"""safety_tester (hipot) library for the Okaya HVT Testbench. Importing this package fires
the registration decorator (INSTRUMENT_LIBRARY.md §5.1) so the library appears in the
registry + index. Requires instrumentlib >= v1.2.0 (the `safety_tester` capability).

Copied from the central Instrument_Library (self-contained fork, TEMPLATE.md §1.2):
`ut5320r` — the UNI-T UT5320R+ hipot/insulation tester. Uses the VISA transport
(`instrument_libs/transports/visa.py`), so `pyvisa` must be installed for the real
(non-simulated) path. VISA/SCPI only — the manual's Modbus register map is read-only for
step results and cannot program a step's voltage/dwell, so it is not used here.
"""

from instrumentlib import instrument_library

from instrument_libs.safety_tester.ut5320r import Ut5320r

instrument_library(
    library_id="ut5320r",
    vendor="UNI-T",
    model="UT5320R+",
    capabilities=["safety_tester"],
    interface_version=1,
    transports=["visa_lan", "visa_usb", "visa_serial"],
    connection_params={
        "resource": {"type": "string"},
        "timeout_ms": {"type": "int", "default": 5000},
        "timeout_s": {"type": "float", "default": 65.0},
        "read_termination": {"type": "string", "default": "\n"},
        "write_termination": {"type": "string", "default": "\n"},
    },
    library_version="1.0.0",
    generated_by="claude-code/create-instrument-library/2026-09",
    manual_reference="UT5300X+ and UT5320R-SxA Series Hipot Tester Programming Manual "
                     "(SCPI&MODBUS RTU) REV.1.0, Feb 2023, UNI-TREND — §1.5 FUNCtion "
                     "(STEP/TYPE + AC/DC/IR setpoints), §1.8 TEST, §1.9 RESET, §1.10 IDN?, "
                     "§1.12 FETCh?. VISA/SCPI path only — the Modbus RTU register map in the "
                     "same manual (Ch.2-3) is read-only for step results and is NOT used here. "
                     "Confirmed on the bench 2026-09 that the unit answers over VISA.",
)(Ut5320r)

__all__ = ["Ut5320r"]

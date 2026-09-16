"""power_source libraries for the Okaya transformer bench. Importing this package fires
the registration decorator (INSTRUMENT_LIBRARY.md §5.1) so the library appears in the
registry + index.

Copied from the central Instrument_Library (self-contained fork, TEMPLATE.md §1.2):
`itech_it7300` — the ITECH IT7322 programmable AC source. Uses the VISA transport
(`instrument_libs/transports/visa.py`), so `pyvisa` must be installed for the real
(non-simulated) path.
"""

from instrumentlib import instrument_library

from instrument_libs.power_source.itech_it7300 import ItechIt7300

instrument_library(
    library_id="itech_it7300",
    vendor="ITECH",
    model="IT7322",
    capabilities=["power_source"],
    interface_version=1,
    transports=["visa_lan", "visa_usb", "visa_serial"],
    connection_params={
        "resource": {"type": "string"},
        "timeout_ms": {"type": "int", "default": 5000},
        "read_termination": {"type": "string", "default": "\n"},
        "write_termination": {"type": "string", "default": "\n"},
    },
    library_version="1.0.0",
    generated_by="claude-code/create-instrument-library/2026-09",
    manual_reference="ITECH IT7300 Series Programming Guide (Manual Art. No. IT7300-402210, Revision 1, "
                     "2018-03-15) — Ch.6 [SOUR:]VOLTage (RMS VAC), Ch.9 MEASure[:SCALar]:{VOLTage|CURRent}[:AC]? "
                     "(<NR2>), Ch.3 CONFig:PROTect:CURRent:RMS (Irms trip = current limit), Ch.7 OUTPut[:STATe], "
                     "Ch.2 SYSTem:REMote (sent on connect). Single-phase IT7321/IT7322/IT7322H/IT7324/IT7324H/"
                     "IT7326/IT7326H share this dialect. Output frequency/waveform are on the hardware but outside "
                     "the IPowerSource scalar contract. NOT hardware-verified (unit 192.168.10.18 unreachable at "
                     "authoring); confirm *IDN? string + command spelling on the bench.",
)(ItechIt7300)

__all__ = ["ItechIt7300"]

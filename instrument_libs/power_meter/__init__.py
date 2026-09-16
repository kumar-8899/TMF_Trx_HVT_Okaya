"""AC meter library for the Okaya HVT Testbench (MECO SMP voltmeter). Importing this package
fires the registration decorator (INSTRUMENT_LIBRARY.md §5.1).

This sim driver uses the transport-bypass shortcut (context-keyed sim values), so the package
is imported directly by the app (like the central `daq` package) rather than pulled into a
top-level conformance sweep. Harden the real Modbus path against the vendor register map and
upstream to the central Instrument_Library to make it conformance-gated + reusable."""

from instrumentlib import instrument_library

from instrument_libs.power_meter.meco_smp72 import MecoSmp72

instrument_library(
    library_id="meco_smp72",
    vendor="MECO",
    model="SMP 72X1445SN-TRMS",
    capabilities=["analog_input"],
    interface_version=1,
    transports=["sim", "modbus_rtu"],
    connection_params={
        "host": {"type": "string", "default": ""},
        "unit_id": {"type": "int", "default": 1},
        "sim_voltage": {"type": "float", "default": 12.0},
    },
    library_version="1.0.0",
    generated_by="claude-code/new-test-app/2026-09",
    manual_reference="MECO SMP 72X1445SN-TRMS Modbus register map — RMS voltage register TODO "
                     "(sim-verified; real register/float decode not yet wired)",
)(MecoSmp72)

__all__ = ["MecoSmp72"]

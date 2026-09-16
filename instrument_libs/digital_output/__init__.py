"""digital_output libraries. Importing this package fires the registration decorator
(INSTRUMENT_LIBRARY.md §5.1) so the library appears in the registry + index."""

from instrumentlib import instrument_library

from instrument_libs.digital_output.waveshare_modbus_relay import WaveshareModbusRelay

instrument_library(
    library_id="waveshare_modbus_relay",
    vendor="Waveshare",
    model="Modbus Relay (N-channel)",
    capabilities=["digital_output", "digital_input"],
    interface_version=1,
    transports=["modbus_rtu_tcp", "modbus_tcp"],
    connection_params={
        "host": {"type": "string"},
        "port": {"type": "int", "default": 4196},
        "unit_id": {"type": "int", "default": 1},
        "num_channels": {"type": "int", "default": 32},
        "timeout_ms": {"type": "int", "default": 5000},
        "framing": {"type": "string", "default": "rtu"},
    },
    library_version="1.0.0",
    generated_by="claude-code/new-test-app/2026-09",
    manual_reference="Waveshare Modbus Relay — coil 0..n-1 (FC01/FC05), DI 0..n-1 (FC02), ver reg "
                     "0x8000 (FC03), RTU-over-TCP; generalises the hardware-verified 8CH (B) driver. "
                     "Confirm channel count + coil map for the bench's specific board.",
)(WaveshareModbusRelay)

__all__ = ["WaveshareModbusRelay"]

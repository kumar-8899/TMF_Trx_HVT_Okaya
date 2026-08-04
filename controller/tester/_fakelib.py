"""A hermetic simulated power-source library for controller tests — registered through
the real instrumentlib decorator so the registry resolves it, but self-contained (no
dependency on the Instrument_Library repo path)."""

from instrumentlib import IPowerSource, InstrumentBase, SimTransport, instrument_library
from instrumentlib.registry import REGISTRY

LIB_ID = "fake_psu_c2"


class FakePsu(InstrumentBase, IPowerSource):
    EXPECTED_IDN = "FAKEPSU"
    _SIM = {"*IDN?": "FAKE,FAKEPSU,1"}

    def __init__(self, instance_id, *, simulated=False, params=None, **kw):
        super().__init__(instance_id, transport=SimTransport(responses=dict(self._SIM)),
                         simulated=True, params=params or {}, **kw)

    async def identify(self):
        return "FAKE,FAKEPSU,1"

    async def measure_voltage(self):
        return 5.0

    async def measure_current(self):
        return 0.1

    async def get_voltage_setpoint(self):
        return 5.0

    async def set_voltage(self, volts):
        self.transport.writes.append(("set_voltage", volts))

    async def set_current_limit(self, amps):
        self.transport.writes.append(("set_current_limit", amps))

    async def output_enable(self, on):
        self.transport.writes.append(("output_enable", on))

    async def safe_state(self):
        pass

    async def emergency_disable(self):
        pass


def ensure_registered() -> str:
    if LIB_ID not in REGISTRY:
        instrument_library(
            library_id=LIB_ID, vendor="Fake", model="PSU", capabilities=["power_source"],
            interface_version=1, transports=["sim"], connection_params={},
            library_version="1.0.0", generated_by="test", manual_reference="test",
        )(FakePsu)
    return LIB_ID

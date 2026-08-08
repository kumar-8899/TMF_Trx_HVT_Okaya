"""Capability interfaces — the generation contract (INSTRUMENT_LIBRARY.md §2).

Each interface lists its method surface + `INTERFACE_VERSION`. Default methods
raise `NotSupported`, so a library overrides only what it implements and interface
growth (§2.3) never breaks existing libraries. A library declares one or more
capabilities in `@instrument_library(capabilities=[…])` and fully implements every
one — a composite/multi-function instrument (e.g. a DMM/DAQ) mixes in several.

Scalar interfaces are reachable via the variable engine; non-scalar ones only via
`capability.request` and MUST NOT be bound in the variable map (§2.2).
"""

from __future__ import annotations

from instrumentlib.errors import NotSupported


class Capability:
    INTERFACE: str = ""
    INTERFACE_VERSION: int = 1
    METHODS: tuple[str, ...] = ()
    SCALAR: bool = True

    def _ns(self, method: str):
        raise NotSupported(f"{method} not supported by {type(self).__name__}", method=method)


# ---- scalar capabilities (variable-engine reachable, §2.1) ----------------

class IPowerSource(Capability):
    INTERFACE, INTERFACE_VERSION = "power_source", 1
    METHODS = ("set_voltage", "get_voltage_setpoint", "measure_voltage",
               "measure_current", "set_current_limit", "output_enable")

    async def set_voltage(self, volts: float): self._ns("set_voltage")
    async def get_voltage_setpoint(self) -> float: self._ns("get_voltage_setpoint")
    async def measure_voltage(self) -> float: self._ns("measure_voltage")
    async def measure_current(self) -> float: self._ns("measure_current")
    async def set_current_limit(self, amps: float): self._ns("set_current_limit")
    async def output_enable(self, on: bool): self._ns("output_enable")


class IElectronicLoad(Capability):
    INTERFACE, INTERFACE_VERSION = "electronic_load", 1
    METHODS = ("set_mode", "set_setpoint", "load_enable",
               "measure_voltage", "measure_current", "measure_power")

    async def set_mode(self, mode: str): self._ns("set_mode")          # "cc"|"cv"|"cr"|"cp"
    async def set_setpoint(self, value: float): self._ns("set_setpoint")
    async def load_enable(self, on: bool): self._ns("load_enable")
    async def measure_voltage(self) -> float: self._ns("measure_voltage")
    async def measure_current(self) -> float: self._ns("measure_current")
    async def measure_power(self) -> float: self._ns("measure_power")


class IAnalogInput(Capability):
    INTERFACE, INTERFACE_VERSION = "analog_input", 1
    METHODS = ("read_voltage",)

    async def read_voltage(self, channel: int) -> float: self._ns("read_voltage")


class IDigitalInput(Capability):
    INTERFACE, INTERFACE_VERSION = "digital_input", 1
    METHODS = ("read_digital",)

    async def read_digital(self, channel: int) -> bool: self._ns("read_digital")


class IDigitalOutput(Capability):
    INTERFACE, INTERFACE_VERSION = "digital_output", 1
    METHODS = ("write_digital", "read_digital_setpoint")

    async def write_digital(self, channel: int, state: bool): self._ns("write_digital")
    async def read_digital_setpoint(self, channel: int) -> bool: self._ns("read_digital_setpoint")


class ITemperature(Capability):
    INTERFACE, INTERFACE_VERSION = "temperature", 1
    METHODS = ("measure_temperature",)

    async def measure_temperature(self, channel: int) -> float: self._ns("measure_temperature")


class IResistance(Capability):
    INTERFACE, INTERFACE_VERSION = "resistance", 1
    METHODS = ("measure_resistance",)

    async def measure_resistance(self, channel: int) -> float: self._ns("measure_resistance")


class IFrequency(Capability):
    INTERFACE, INTERFACE_VERSION = "frequency", 1
    METHODS = ("measure_frequency",)

    async def measure_frequency(self, channel: int) -> float: self._ns("measure_frequency")


# ---- non-scalar capabilities (capability.request only, §2.2) --------------

class Multiplexer(Capability):
    INTERFACE, INTERFACE_VERSION, SCALAR = "multiplexer", 1, False
    METHODS = ("set_route", "open_all", "get_routes")

    async def set_route(self, channel: int, bus: str): self._ns("set_route")
    async def open_all(self): self._ns("open_all")
    async def get_routes(self) -> list: self._ns("get_routes")


class DSO(Capability):
    INTERFACE, INTERFACE_VERSION, SCALAR = "dso", 1, False
    METHODS = ("configure", "capture")

    async def configure(self, **kw): self._ns("configure")
    async def capture(self):  # -> WaveformRecord (wire shape is an open item, §Open)
        self._ns("capture")


class ISafetyTester(Capability):
    """Hipot / electrical-safety tester (e.g. UT5320R+). Non-scalar: a measurement runs a
    program step and returns a value plus, for AC withstand, a breakdown flag — so it is
    reached via `capability.request` / `ctx.invoke`, never bound as a scalar signal."""
    INTERFACE, INTERFACE_VERSION, SCALAR = "safety_tester", 1, False
    METHODS = ("measure_ir", "measure_acw")

    async def measure_ir(self, voltage: float, step: int = 1) -> float:
        """Insulation resistance at `voltage` (program `step`) → MΩ."""
        self._ns("measure_ir")

    async def measure_acw(self, voltage: float, dwell: float, step: int = 1) -> tuple:
        """AC withstand at `voltage` for `dwell` s (program `step`) → (leakage_mA, breakdown)."""
        self._ns("measure_acw")


_ALL = (IPowerSource, IElectronicLoad, IAnalogInput, IDigitalInput,
        IDigitalOutput, ITemperature, IResistance, IFrequency, Multiplexer, DSO, ISafetyTester)

CAPABILITIES: dict[str, type[Capability]] = {c.INTERFACE: c for c in _ALL}
SCALAR_CAPABILITIES = {c.INTERFACE for c in _ALL if c.SCALAR}
NON_SCALAR_CAPABILITIES = {c.INTERFACE for c in _ALL if not c.SCALAR}

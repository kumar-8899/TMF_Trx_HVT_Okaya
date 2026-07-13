"""TEMPLATE — copy to instrument_libs/<capability>/<library_id>.py and fill in.

Example shown for an electronic_load; swap the CMD table + methods for the chosen
capability (see reference/capabilities.md). Keep the class thin: device specifics only.
Registration (@instrument_library) goes in the sub-package __init__.py, not here.
"""

from __future__ import annotations

from instrumentlib import InstrumentBase, IElectronicLoad, SimTransport   # swap the interface
from instrumentlib.errors import GarbageResponse

from instrument_libs.transports import VisaTransport   # or another transport under transports/


class VENDOR_MODEL(InstrumentBase, IElectronicLoad):   # rename; (InstrumentBase, I<Capability>)
    EXPECTED_IDN = "<model-substring>"                 # re-verified on reconnect

    # ---- command table: EVERY command string, from the vendor manual (§4.3) ----
    CMD = {
        "idn":     "*IDN?",
        "mode":    "MODE {m}",
        "setp":    "CURR {v:.4f}",
        "load":    "LOAD {s}",
        "meas_v":  "MEAS:VOLT?",
        "meas_i":  "MEAS:CURR?",
        "meas_p":  "MEAS:POW?",
    }

    # ---- plausible sim responses (reads parse cleanly; IDN carries the model) ----
    _SIM = {
        "*IDN?":      "<Vendor>,<Model>,<serial>,<fw>",
        "MEAS:VOLT?": "12.0000",
        "MEAS:CURR?": "1.5000",
        "MEAS:POW?":  "18.0000",
    }

    def __init__(self, instance_id: str, *, simulated: bool = False, params: dict | None = None, **kw):
        params = params or {}
        transport = (SimTransport(responses=dict(self._SIM)) if simulated
                     else VisaTransport(params["resource"], timeout_ms=params.get("timeout_ms", 5000)))
        super().__init__(instance_id, transport=transport, simulated=simulated, params=params, **kw)

    async def identify(self) -> str:
        return await self.transport.query(self.CMD["idn"])

    # ---- capability methods (implement ALL of them) ----------------------------

    async def set_mode(self, mode: str):
        await self.transport.write(self.CMD["mode"].format(m=mode.upper()))

    async def set_setpoint(self, value: float):
        await self.transport.write(self.CMD["setp"].format(v=float(value)))

    async def load_enable(self, on: bool):
        await self.transport.write(self.CMD["load"].format(s="ON" if on else "OFF"))

    async def measure_voltage(self) -> float:
        return self._num(await self.transport.query(self.CMD["meas_v"]), "measure_voltage")

    async def measure_current(self) -> float:
        return self._num(await self.transport.query(self.CMD["meas_i"]), "measure_current")

    async def measure_power(self) -> float:
        return self._num(await self.transport.query(self.CMD["meas_p"]), "measure_power")

    # ---- mandatory base surface -----------------------------------------------

    async def safe_state(self):
        await self.transport.write(self.CMD["load"].format(s="OFF"))

    async def emergency_disable(self):
        await self.transport.write(self.CMD["load"].format(s="OFF"))

    # ---- helper: a read must be a value or an error, never a wrong number -------

    def _num(self, raw: str, method: str) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError) as e:
            raise GarbageResponse(f"implausible reading {raw!r}", instance_id=self.instance_id,
                                  method=method) from e


# In instrument_libs/<capability>/__init__.py:
#
#   from instrumentlib import instrument_library
#   from instrument_libs.<capability>.<library_id> import VENDOR_MODEL
#
#   instrument_library(
#       library_id="<library_id>", vendor="<Vendor>", model="<Model>",
#       capabilities=["electronic_load"], interface_version=1,   # a list; composite names several
#       transports=["visa_lan"], connection_params={"resource": {"type": "string"},
#                                                    "timeout_ms": {"type": "int", "default": 5000}},
#       library_version="1.0.0", generated_by="claude-code/<yyyy-mm>",
#       manual_reference="<Vendor Manual vX.Y>",
#   )(VENDOR_MODEL)

"""MECO SMP 72X1445SN-TRMS — programmable AC voltmeter (Modbus), analog_input.

On the Okaya HVT Testbench this reads the **small feedback-winding voltage** — a range low
enough that a dedicated true-RMS voltmeter measures it. Single scalar capability: analog_input
(`read_voltage`). Real hardware reads one input; the `context` arg is accepted only so the
same variable-map convention as other analog_input drivers applies.

SIMULATION is transport-bypass (like the central `daq` drivers): a representative feedback
voltage with light noise, overridable via the `sim_voltage` param. Imported directly by the
app rather than swept by top-level conformance.

REAL HARDWARE (TODO — from the MECO SMP Modbus register map, not yet wired): map the RMS-voltage
register(s) (typically a 32-bit float pair) and extend the Modbus transport with a float read,
or add a Modbus-RTU serial transport. Keep the `read_voltage` signature.
"""

from __future__ import annotations

import random

from instrumentlib import IAnalogInput, InstrumentBase, SimTransport


class MecoSmp72(InstrumentBase, IAnalogInput):
    EXPECTED_IDN = None
    _SIM = {"*IDN?": "MECO,SMP-72X1445SN,SIM,1"}

    def __init__(self, instance_id, *, simulated=False, params=None, on_command=None, **kw):
        params = params or {}
        self._sim_v = float(params.get("sim_voltage", 12.0))
        super().__init__(instance_id, transport=SimTransport(responses=dict(self._SIM)),
                         simulated=True, params=params, on_command=on_command, **kw)

    async def identify(self):
        return "MECO,SMP-72X1445SN,SIM,1"

    async def read_voltage(self, channel: int, context: str | None = None) -> float:
        return self._sim_v + random.uniform(-0.002, 0.002) * (abs(self._sim_v) or 1.0)

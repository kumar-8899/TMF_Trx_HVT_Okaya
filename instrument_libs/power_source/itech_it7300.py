"""ITECH IT7300 series programmable AC power source — IPowerSource (SCPI).

Single-phase programmable AC source (IT7321 / IT7322 / IT7322H / IT7324 / IT7324H /
IT7326 / IT7326H — one SCPI dialect). This library drives the AC output as an
IPowerSource: the scalar setpoints / readbacks are the AC RMS voltage, the AC RMS
current readback, an RMS overcurrent trip used as the "current limit", and the output
on/off. Output FREQUENCY, waveform, phase, LIST / SWEEP sequence modes and the TRACe
data buffer all exist on the hardware but are NOT part of the IPowerSource scalar
contract, so they are intentionally not exposed here (frequency would land as a
non-scalar `ac_source` capability later, once the framework grows one — same call the
EEC 8520 sibling made). All wire strings live in the CMD table below — the 5-minute
human diff against the vendor manual (INSTRUMENT_LIBRARY.md §4.3). Sim + conformance
run headless (no pyvisa, no hardware).

Transport (Programming Guide §1.6): LAN is a raw TCP socket whose port is set in the
unit's System > LAN menu ("SocketPort"; ITECH default 30000) — VISA SOCKET resource,
e.g. "TCPIP0::192.168.10.18::30000::SOCKET". USB enumerates as USB-TMC
("USB0::...::INSTR"); RS-232 is a DB9 at 9600 8N1 by default ("ASRLn::INSTR").
Command strings are <NL>-terminated and queries return a bare numeric <NR2> with no
unit suffix (Programming Guide "Command terminator" + Ch.9). Termination chars are
`params` overrides for a unit configured differently.

Remote gate (Programming Guide, SYSTem:REMote): the IT7300 ignores / errors on
control commands until it has been put in remote — so `connect()` (and every
reconnect) sends `SYST:REM` first. No-op in simulation.

Dialect: SCPI per the ITECH IT7300 Series Programming Guide (Manual Art. No.
IT7300-402210, Revision 1, 2018-03-15) — Ch.6 Voltage, Ch.4 Frequency, Ch.7 Output,
Ch.9 Measurement, Ch.3 Configuration (Irms protection), Ch.14 IEEE-488.2.
HARDWARE-VERIFIED 2026-09 against the unit at 192.168.10.18:30000 (VISA SOCKET,
NI-VISA backend): *IDN? -> "ITECH Electronics, IT7322, 800784011807830009,
1.19-1.26"; set_voltage/get_voltage_setpoint/output_enable/measure_voltage/
measure_current all confirmed over the live link (20 V RMS, no load: setpoint
readback 20.0, measured 19.9 V / 61 uA).
"""

from __future__ import annotations

from instrumentlib import InstrumentBase, IPowerSource, SimTransport
from instrumentlib.errors import GarbageResponse

from instrument_libs.transports import VisaTransport


class ItechIt7300(InstrumentBase, IPowerSource):
    # *IDN? verified live (see module docstring) -> "ITECH Electronics, IT7322, ...".
    EXPECTED_IDN = "IT7322"

    # ITECH IT7300 SCPI command table (Programming Guide IT7300-402210 Rev.1) — the
    # review surface. Values are sent space-separated, unit-less (Ch.1 "Space").
    CMD = {
        "idn":     "*IDN?",                       # Ch.14 *IDN?
        "remote":  "SYST:REM",                    # Ch.2 SYSTem:REMote — required before control
        "set_v":   "VOLT {v:.2f}",                # Ch.6 [SOUR:]VOLT[:LEV][:IMM][:AMPL]  RMS VAC
        "get_v":   "VOLT?",
        "meas_v":  "MEAS:VOLT:AC?",               # Ch.9 MEASure[:SCALar]:VOLTage[:AC]?  -> <NR2> Vrms
        "meas_i":  "MEAS:CURR:AC?",               # Ch.9 MEASure[:SCALar]:CURRent[:AC]?  -> <NR2> Arms
        "ilim":    "CONF:PROT:CURR:RMS {a:.2f}",  # Ch.3 CONFig:PROTect:CURRent:RMS  (Irms trip point)
        "out":     "OUTP {s}",                    # Ch.7 OUTPut[:STATe]  ON | OFF
    }

    # Plausible sim responses (§3): one entry per query the methods issue. Reads parse
    # to floats; *IDN? carries a representative ITECH string (format not manual-confirmed).
    _SIM = {
        "*IDN?":         "ITECH Ltd., IT7322, 000000000000000, 1.00-1.00",
        "VOLT?":         "220.00",
        "MEAS:VOLT:AC?": "219.98",
        "MEAS:CURR:AC?": "0.150",
    }

    def __init__(self, instance_id: str, *, simulated: bool = False, params: dict | None = None, **kw):
        params = params or {}
        if simulated:
            transport = SimTransport(responses=dict(self._SIM))
        else:
            # LAN: "TCPIP0::<ip>::<socketport>::SOCKET" (ITECH default 30000); USB: the
            # USB-TMC "USB0::...::INSTR"; RS-232: "ASRLn::INSTR" (9600 8N1). All links
            # are <NL>-terminated; override the termination via params if a unit differs.
            transport = VisaTransport(
                params["resource"],
                timeout_ms=params.get("timeout_ms", 5000),
                read_termination=params.get("read_termination", "\n"),
                write_termination=params.get("write_termination", "\n"),
            )
        super().__init__(instance_id, transport=transport, simulated=simulated, params=params, **kw)

    # ---- connection: the IT7300 needs SYST:REM before it accepts control ----

    async def connect(self) -> None:
        await super().connect()
        await self._enter_remote()

    async def on_reconnect(self) -> None:
        await self._enter_remote()
        await super().on_reconnect()

    async def _enter_remote(self) -> None:
        if not self.simulated:
            await self.transport.write(self.CMD["remote"])

    # ---- identity ---------------------------------------------------------

    async def identify(self) -> str:
        return await self.transport.query(self.CMD["idn"])

    # ---- IPowerSource ---------------------------------------------------

    async def set_voltage(self, volts: float):
        await self.transport.write(self.CMD["set_v"].format(v=float(volts)))

    async def get_voltage_setpoint(self) -> float:
        return self._num(await self.transport.query(self.CMD["get_v"]), "get_voltage_setpoint")

    async def measure_voltage(self) -> float:
        return self._num(await self.transport.query(self.CMD["meas_v"]), "measure_voltage")

    async def measure_current(self) -> float:
        return self._num(await self.transport.query(self.CMD["meas_i"]), "measure_current")

    async def set_current_limit(self, amps: float):
        # The IT7300 regulates voltage; "current limit" maps to the RMS overcurrent
        # PROTECTION trip (Irms-Protect), the closest scalar analogue on an AC source.
        await self.transport.write(self.CMD["ilim"].format(a=float(amps)))

    async def output_enable(self, on: bool):
        await self.transport.write(self.CMD["out"].format(s="ON" if on else "OFF"))

    # ---- mandatory base surface (§3) --------------------------------------

    async def safe_state(self):
        await self.transport.write(self.CMD["out"].format(s="OFF"))

    async def emergency_disable(self):
        await self.transport.write(self.CMD["out"].format(s="OFF"))

    # ---- helpers --------------------------------------------------------

    def _num(self, raw: str, method: str) -> float:
        """Error-not-value rule (§4.4): an implausible reading is an error, never a number."""
        try:
            return float(raw)
        except (TypeError, ValueError) as e:
            raise GarbageResponse(f"implausible reading {raw!r}", instance_id=self.instance_id,
                                  method=method) from e

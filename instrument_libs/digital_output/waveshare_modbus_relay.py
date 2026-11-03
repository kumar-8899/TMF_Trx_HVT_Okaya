"""Waveshare Modbus Relay card (N-channel) — a COMPOSITE DIO module.

On the Okaya transformer bench this card does the **measurement multiplexing**: its relays
route Primary / Secondary / Feedback / Winding taps onto the meter inputs, and drive the
tower-light / buzzer lines. Channel == the Modbus coil address (0-based): silkscreen R1..Rn
map to coil 0..n-1. Relays are Modbus **coils** (FC05 write, FC01 read-back); the isolated
digital inputs are **discrete inputs** (FC02). The library declares TWO capabilities
(INSTRUMENT_LIBRARY.md §4.1) — digital_output + digital_input — over ONE Modbus connection.

This is the N-channel generalisation of the central `waveshare_8ch_relay_b` driver: the bench
board carries more than eight relays (R1..R18 + K2 + spares), so the channel count is a
connection param (`num_channels`, default 32). All wire commands live in the CMD table below
— the 5-minute human diff against the Waveshare manual (§4.3).

Wire dialect follows the verified central driver: Modbus **RTU-over-TCP** (serial-to-Ethernet
bridge, default port 4196, unit 1) — relay control = FC05 write-single-coil (0xFF00 ON /
0x0000 OFF), read-back = FC01, digital inputs = FC02, version = FC03 holding reg 0x8000. A
native Modbus/TCP unit overrides `port=502, framing="tcp"`; a USB Modbus-RTU board is a
different transport (not wired here). Confirm the coil map for your specific board.
Sim + conformance run headless (no card).
"""

from __future__ import annotations

import asyncio

from instrumentlib import IDigitalInput, IDigitalOutput, InstrumentBase, SimTransport
from instrumentlib.errors import DeviceError, GarbageResponse, NotSupported

from instrument_libs.transports import ModbusTcpTransport


class WaveshareModbusRelay(InstrumentBase, IDigitalOutput, IDigitalInput):
    # No Modbus identity string exists; identify() proves the link via the version
    # register, and EXPECTED_IDN is None so reconnect never trips IdentityMismatch.
    EXPECTED_IDN = None

    # Modbus command grammar decoded by ModbusTcpTransport: R3 read holding reg,
    # R1 read coil, R2 read discrete input, W5 write single coil. {ch} = 0-based address.
    CMD = {
        "ver":        "R3 0x8000",
        "read_coil":  "R1 {ch}",
        "read_di":    "R2 {ch}",
        "write_coil": "W5 {ch} {s}",
    }

    # Plausible sim responses (§3): version token; coils/DI read back de-energised/idle.
    _SIM = {
        "R3*": "10",
        "R1*": "0",
        "R2*": "0",
    }

    def __init__(self, instance_id: str, *, simulated: bool = False, params: dict | None = None, **kw):
        params = params or {}
        self._ch_max = int(params.get("num_channels", 32)) - 1
        if simulated:
            transport = SimTransport(responses=dict(self._SIM))
        else:
            transport = ModbusTcpTransport(
                params["host"],
                port=params.get("port", 4196),
                unit_id=params.get("unit_id", 1),
                timeout_ms=params.get("timeout_ms", 5000),
                framing=params.get("framing", "rtu"),
            )
        super().__init__(instance_id, transport=transport, simulated=simulated, params=params, **kw)

    async def identify(self) -> str:
        ver = (await self.transport.query(self.CMD["ver"])).strip()
        return f"Waveshare Modbus Relay {self._ch_max + 1}CH (fw {ver})"

    def _addr(self, channel: int, method: str) -> int:
        ch = int(channel)
        if ch < 0 or ch > self._ch_max:
            raise NotSupported(f"channel {ch} out of range 0..{self._ch_max}",
                               instance_id=self.instance_id, method=method)
        return ch

    # ---- IDigitalOutput (relays) ------------------------------------------

    async def write_digital(self, channel: int, state: bool):
        ch = self._addr(channel, "write_digital")
        await self.transport.write(self.CMD["write_coil"].format(ch=ch, s="ON" if state else "OFF"))

    async def read_digital_setpoint(self, channel: int) -> bool:
        ch = self._addr(channel, "read_digital_setpoint")
        return self._bool(await self.transport.query(self.CMD["read_coil"].format(ch=ch)),
                          "read_digital_setpoint")

    # ---- IDigitalInput (isolated inputs) ----------------------------------

    async def read_digital(self, channel: int) -> bool:
        ch = self._addr(channel, "read_digital")
        return self._bool(await self.transport.query(self.CMD["read_di"].format(ch=ch)), "read_digital")

    async def digital_input(self, channel: int) -> bool:
        """Read one isolated digital input (FC02 discrete input) by channel NUMBER — the
        variable-map form for a physical input (push-button, light-curtain, E-stop). Reads
        the real input state, unlike `read_digital_setpoint` which plays back a coil's own
        commanded value. Delegates to `read_digital` (same wire path)."""
        return await self.read_digital(channel)

    # ---- mandatory base surface (all relays de-energised = safe) ----------

    async def safe_state(self):
        for ch in range(self._ch_max + 1):
            try:
                await self.transport.write(self.CMD["write_coil"].format(ch=ch, s="OFF"))
            except DeviceError as exc:
                if self._is_absent_coil(exc):
                    break                        # past the real coils (num_channels set too high)
                raise

    @staticmethod
    def _is_absent_coil(exc: DeviceError) -> bool:
        """True when the board rejected a coil address as illegal (Modbus exception 0x02) — i.e.
        the board has no such coil. Coils are contiguous 0..n-1, so the first illegal address marks
        the end of the real board, and an all-coils sweep can stop there instead of failing. This
        guards against `num_channels` configured higher than the card really has (its default is 32;
        this bench's routing card is 8ch), which would otherwise fail the whole interlock and block
        the test before anything energises."""
        return getattr(exc, "code", None) == "modbus:illegal_data_address"

    async def emergency_disable(self):
        await self.safe_state()

    # ---- multiplexer interlock: prove every coil is OPEN, with read-back ----

    async def open_all_verified(self, settle_s: float = 0.3, retries: int = 2) -> dict:
        """Drive EVERY relay coil OFF (FC05) and then FC01 read-back each one to CONFIRM it
        reports open. Any coil that does not read open — a dropped/ignored write that left a
        contactor energised (the two-contactors-on fault on this bench) — has its OFF re-issued
        and is re-read, up to `retries` further passes. If a coil is still closed after that,
        raise DeviceError naming the channel(s): the caller must NOT energise a new route on top
        of a live one (r3 safety). `settle_s` is waited once after each round of OFF writes,
        before the read-back, to let the module (and any mechanical contactor) settle.

        NOTE on what the read-back proves: FC01 returns the relay MODULE's own coil register, not
        the external contactor's mechanical position. It catches a LOST or ignored OFF command (the
        coil is still energised), NOT a contactor that merely drops out slowly after its coil went
        cold — a real inter-step dead-time (the step's settle_off_s) is what covers that case."""
        present: list[int] | None = None        # discovered on the first OFF sweep (see _is_absent_coil)
        pending: list[int] = []
        for _ in range(max(1, int(retries) + 1)):
            targets = pending if present is not None else range(self._ch_max + 1)
            written: list[int] = []
            for ch in targets:
                try:
                    await self.transport.write(self.CMD["write_coil"].format(ch=ch, s="OFF"))
                except DeviceError as exc:
                    if present is None and self._is_absent_coil(exc):
                        break                    # real board ends here; stop sweeping ghost coils
                    raise
                written.append(ch)
            if present is None:
                present = written
                pending = written
                if not present:
                    raise DeviceError(
                        "relay card rejected coil 0 as an illegal address — no coils to open "
                        "(check num_channels / wiring)",
                        instance_id=self.instance_id, method="open_all_verified")
            if settle_s > 0:
                await asyncio.sleep(float(settle_s))
            still_closed = [ch for ch in pending
                            if self._bool(await self.transport.query(self.CMD["read_coil"].format(ch=ch)),
                                          "open_all_verified")]
            pending = still_closed
            if not pending:
                return {"channels": len(present), "verified_open": True}
        raise DeviceError(
            f"relay coil(s) {pending} still read CLOSED after {int(retries) + 1} open "
            f"attempt(s) — refusing to energise a route over a live contactor",
            instance_id=self.instance_id, method="open_all_verified")

    # ---- helper: a read is a value or an error, never a wrong bit ----------

    def _bool(self, raw: str, method: str) -> bool:
        s = (raw or "").strip()
        if s in ("0", "1"):
            return s == "1"
        raise GarbageResponse(f"implausible digital reading {raw!r}",
                              instance_id=self.instance_id, method=method)

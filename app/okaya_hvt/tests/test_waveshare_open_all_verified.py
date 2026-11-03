"""waveshare_modbus_relay.open_all_verified — the mux interlock: drive every coil OFF (FC05),
read each back (FC01), and refuse (DeviceError) if any coil will not read open. This is what the
hipot_acw step calls before energising a route, so a tap is never closed over a live contactor
(the confirmed two-contactors-on fault). A dropped OFF write (a coil that ignores it) is re-issued
up to `retries` times before the interlock fails."""

from __future__ import annotations

import asyncio

import pytest

from instrument_libs.digital_output.waveshare_modbus_relay import WaveshareModbusRelay
from instrumentlib.errors import DeviceError


class FakeModbus:
    """Minimal FC05/FC01 relay model. `ignores` maps a channel -> how many OFF writes it drops
    (a stuck/slow coil that keeps reading CLOSED); `preset` seeds coils already energised."""

    def __init__(self, ignores=None, preset=()):
        self.coils = {ch: True for ch in preset}
        self.ignores = dict(ignores or {})
        self.writes: list[str] = []
        self.reads: list[str] = []

    async def write(self, cmd):                 # "W5 {ch} ON|OFF"
        self.writes.append(cmd)
        _, ch, state = cmd.split()
        ch = int(ch)
        if state == "OFF" and self.ignores.get(ch, 0) > 0:
            self.ignores[ch] -= 1               # this OFF is dropped on the wire
        else:
            self.coils[ch] = (state == "ON")

    async def query(self, cmd):                 # "R1 {ch}" -> coil state
        self.reads.append(cmd)
        _, ch = cmd.split()
        return "1" if self.coils.get(int(ch)) else "0"

    async def connect(self): ...
    async def disconnect(self): ...


def _drv(ignores=None, preset=()):
    d = WaveshareModbusRelay("relay1", simulated=True, params={"num_channels": 8})
    d.simulated = False
    d.transport = FakeModbus(ignores, preset)
    return d


def _run(coro):
    return asyncio.run(coro)


def test_all_coils_driven_off_and_read_back_open():
    d = _drv(preset=(0, 2, 5))                 # three coils start energised
    out = _run(d.open_all_verified(settle_s=0, retries=2))
    assert out == {"channels": 8, "verified_open": True}
    assert [c for c in d.transport.writes if c.endswith("OFF")]  # OFF issued
    assert all(v is False for v in d.transport.coils.values())   # every coil now open
    # one FC01 read per channel on the single clean pass
    assert sum(1 for r in d.transport.reads if r.startswith("R1")) == 8


def test_a_dropped_off_write_is_re_issued_and_then_verifies():
    d = _drv(ignores={3: 1}, preset=(3,))      # ch3 ignores its FIRST OFF, then accepts
    out = _run(d.open_all_verified(settle_s=0, retries=2))
    assert out["verified_open"] is True
    assert d.transport.coils[3] is False       # cleared on the retry
    # ch3 was written OFF at least twice (first dropped, second took)
    assert sum(1 for w in d.transport.writes if w == "W5 3 OFF") >= 2


def test_a_permanently_stuck_coil_raises_naming_the_channel():
    d = _drv(ignores={4: 99}, preset=(4,))     # ch4 never accepts OFF
    with pytest.raises(DeviceError, match=r"\[4\]"):
        _run(d.open_all_verified(settle_s=0, retries=2))


def test_sim_mode_reports_all_open_without_a_board():
    d = WaveshareModbusRelay("relay1", simulated=True, params={"num_channels": 8})
    out = _run(d.open_all_verified(settle_s=0, retries=1))      # SimTransport R1 -> "0"
    assert out == {"channels": 8, "verified_open": True}

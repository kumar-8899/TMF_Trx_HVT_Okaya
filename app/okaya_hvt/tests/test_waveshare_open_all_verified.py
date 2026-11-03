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

    def __init__(self, ignores=None, preset=(), absent_from=None):
        self.coils = {ch: True for ch in preset}
        self.ignores = dict(ignores or {})
        self.absent_from = absent_from          # coils at/after this address don't exist (0x02)
        self.writes: list[str] = []
        self.reads: list[str] = []

    def _check_present(self, ch):
        if self.absent_from is not None and ch >= self.absent_from:
            raise DeviceError("Modbus exception 0x02", code="modbus:illegal_data_address",
                              detail="fn=0x05")

    async def write(self, cmd):                 # "W5 {ch} ON|OFF"
        self.writes.append(cmd)
        _, ch, state = cmd.split()
        ch = int(ch)
        self._check_present(ch)
        if state == "OFF" and self.ignores.get(ch, 0) > 0:
            self.ignores[ch] -= 1               # this OFF is dropped on the wire
        else:
            self.coils[ch] = (state == "ON")

    async def query(self, cmd):                 # "R1 {ch}" -> coil state
        self.reads.append(cmd)
        _, ch = cmd.split()
        self._check_present(int(ch))
        return "1" if self.coils.get(int(ch)) else "0"

    async def connect(self): ...
    async def disconnect(self): ...


def _drv(ignores=None, preset=(), num_channels=8, absent_from=None):
    d = WaveshareModbusRelay("relay1", simulated=True, params={"num_channels": num_channels})
    d.simulated = False
    d.transport = FakeModbus(ignores, preset, absent_from=absent_from)
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


def test_num_channels_set_higher_than_the_board_auto_bounds_at_the_first_absent_coil():
    # The field defect: relay1 took the driver default num_channels=32 but the card is 8ch, so the
    # sweep wrote coil 8, the board answered Modbus 0x02 (illegal data address), and the whole
    # interlock failed -> test FAIL before anything energised. Now the sweep stops at the first
    # absent coil and verifies only the coils that exist.
    d = _drv(num_channels=32, absent_from=8, preset=(0, 3))
    out = _run(d.open_all_verified(settle_s=0, retries=2))
    assert out == {"channels": 8, "verified_open": True}       # 0..7 real, 8..31 ghost -> bounded
    assert all(v is False for v in d.transport.coils.values())  # the real coils were opened
    # it stopped at the first ghost: coil 9+ was never written or read
    assert not any(w.startswith("W5 9 ") for w in d.transport.writes)
    assert not any(r == "R1 9" for r in d.transport.reads)


def test_coil_zero_rejected_as_absent_is_a_real_error_not_a_silent_pass():
    # If even coil 0 is illegal, something is genuinely wrong (wrong unit / wiring) — do NOT report
    # a clean open. The interlock must fail loudly rather than wave through an unverified board.
    d = _drv(num_channels=8, absent_from=0)
    with pytest.raises(DeviceError, match="no coils to open"):
        _run(d.open_all_verified(settle_s=0, retries=2))


def test_sim_mode_reports_all_open_without_a_board():
    d = WaveshareModbusRelay("relay1", simulated=True, params={"num_channels": 8})
    out = _run(d.open_all_verified(settle_s=0, retries=1))      # SimTransport R1 -> "0"
    assert out == {"channels": 8, "verified_open": True}

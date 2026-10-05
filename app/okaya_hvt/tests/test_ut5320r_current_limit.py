"""ut5320r: the recipe's current limit must reach the tester (FUNC:AC:UPPC, manual §1.5.11) —
before this it was only judged in software and the tester kept its front-panel 1 mA limit."""

from __future__ import annotations

import asyncio

import pytest

from instrument_libs.safety_tester.ut5320r import Ut5320r
from instrumentlib.errors import DeviceError


class FakeTransport:
    def __init__(self, uppc_readback="10.000"):
        self.log: list[tuple[str, str]] = []
        self.uppc_readback = uppc_readback

    async def write(self, cmd):
        self.log.append(("w", cmd))

    async def query(self, cmd):
        self.log.append(("q", cmd))
        if cmd.startswith("FUNC:AC:UPPC?"):
            return self.uppc_readback
        if cmd == "FETCh?":    # in progress, then done (the staleness gate needs both)
            n = sum(1 for k, c in self.log if c == "FETCh?")
            return "1,AC,1.000,3.200" if n == 1 else "1,AC,1.000,3.200,PASS"
        raise AssertionError(cmd)

    async def connect(self): ...
    async def disconnect(self): ...


def _drv(readback="10.000"):
    d = Ut5320r("hipot", simulated=True)       # sim only to skip VISA construction ...
    d.simulated = False                         # ... then behave like real hardware
    d.transport = FakeTransport(readback)
    return d


def _run(coro):
    return asyncio.run(coro)


def test_limit_is_programmed_after_type_volt_ttim_and_before_test_then_read_back():
    d = _drv()
    leak, brk = _run(d.measure_acw(1500, 3.0, 1, current_limit_ma=10.0))
    cmds = [c for _, c in d.transport.log]
    assert cmds[:5] == ["FUNC:TYPE 1,AC", "FUNC:AC:VOLT 1,1500", "FUNC:AC:TTIM 1,3.0",
                        "FUNC:AC:UPPC 1,10.000", "FUNC:AC:UPPC? 1"]
    assert cmds.index("TEST") > cmds.index("FUNC:AC:UPPC? 1")      # limit set BEFORE HV starts
    assert (leak, brk) == (3.2, False)


def test_without_a_limit_nothing_is_sent_for_it():
    d = _drv()
    _run(d.measure_acw(1500, 3.0, 1))
    assert not any("UPPC" in c for _, c in d.transport.log)


def test_readback_mismatch_is_an_error_and_no_test_starts():
    d = _drv(readback="1.000")                  # tester ignored the write (still its 1 mA)
    with pytest.raises(DeviceError, match="did not apply"):
        _run(d.measure_acw(1500, 3.0, 1, current_limit_ma=10.0))
    assert ("w", "TEST") not in d.transport.log


@pytest.mark.parametrize("bad", [0.0, 0.0005, 20.01, 50.0])
def test_out_of_range_limit_is_refused_not_clamped(bad):
    d = _drv()
    with pytest.raises(DeviceError, match="outside"):
        _run(d.measure_acw(1500, 3.0, 1, current_limit_ma=bad))
    assert not any("UPPC" in c for _, c in d.transport.log)


def test_range_edges_accepted():
    for ok in (0.001, 20.0):
        d = _drv(readback=f"{ok:.3f}")
        _run(d.measure_acw(1500, 3.0, 1, current_limit_ma=ok))

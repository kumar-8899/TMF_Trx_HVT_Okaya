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
        self.range_readback = "AUTO"

    async def write(self, cmd):
        self.log.append(("w", cmd))

    async def query(self, cmd):
        self.log.append(("q", cmd))
        if cmd.startswith("FUNC:AC:UPPC?"):
            return self.uppc_readback
        if cmd.startswith("FUNC:AC:RANG?"):
            return self.range_readback
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
    assert cmds[:7] == ["FUNC:TYPE 1,AC", "FUNC:AC:VOLT 1,1500", "FUNC:AC:TTIM 1,3.0",
                        "FUNC:AC:UPPC 1,10.000", "FUNC:AC:UPPC? 1",
                        "FUNC:AC:RANG 1,AUTO", "FUNC:AC:RANG? 1"]
    assert cmds.index("TEST") > cmds.index("FUNC:AC:RANG? 1")      # limit + range set BEFORE HV starts
    assert (leak, brk) == (3.2, False)


def test_range_is_forced_to_auto_with_a_limit_and_a_fixed_readback_is_an_error():
    d = _drv()
    d.transport.range_readback = "FIXED"        # tester kept the coarse range -> low leakage reads 0.000
    with pytest.raises(DeviceError, match="AUTO current range"):
        _run(d.measure_acw(1500, 3.0, 1, current_limit_ma=10.0))
    assert ("w", "TEST") not in d.transport.log


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


# ---- a reply left in the socket buffer must not fail the NEXT test (seen live, 2026-10) --------

STALE = "1,AC,0.501,0.055,PASS;"      # the previous test's final FETCh? line, never read


class LaggingTransport(FakeTransport):
    """Real-hardware symptom: one unread reply is waiting, so the next query reads IT."""

    def __init__(self, has_drain: bool):
        super().__init__()
        self.stale = [STALE]
        if has_drain:
            self.drain = self._drain

    async def _drain(self):
        n = sum(len(s) for s in self.stale)
        self.stale.clear()
        return n

    async def query(self, cmd):
        if self.stale:
            self.log.append(("q", cmd))
            return self.stale.pop(0)
        return await super().query(cmd)


def _lagging(has_drain):
    d = Ut5320r("hipot", simulated=True)
    d.simulated = False
    d.transport = LaggingTransport(has_drain)
    return d


def test_stale_reply_is_drained_before_the_readback():
    d = _lagging(has_drain=True)
    leak, _ = _run(d.measure_acw(1500, 3.0, 1, current_limit_ma=10.0))
    assert leak == 3.2
    assert [c for k, c in d.transport.log if k == "q"][0] == "FUNC:AC:UPPC? 1"   # first query is OURS


def test_stale_reply_without_drain_is_discarded_and_readback_retried():
    d = _lagging(has_drain=False)                 # transport that cannot drain
    leak, _ = _run(d.measure_acw(1500, 3.0, 1, current_limit_ma=10.0))
    assert leak == 3.2
    assert [c for k, c in d.transport.log if k == "q"][:2] == ["FUNC:AC:UPPC? 1"] * 2


def test_visa_drain_reads_until_the_line_is_quiet_and_restores_the_timeout():
    from instrument_libs.transports.visa import VisaTransport
    from pyvisa import errors

    class Inst:
        timeout = 5000
        chunks = [b"1,AC,0.501,0.055,PASS;\r\n", b"x\r\n"]

        def read_raw(self):
            if self.chunks:
                assert self.timeout == 50           # short wait while draining
                return self.chunks.pop(0)
            raise errors.VisaIOError(errors.StatusCode.error_timeout)

    t = VisaTransport("TCPIP0::1.2.3.4::502::SOCKET")
    t._inst = Inst()
    assert _run(t.drain()) == 24 + 3
    assert t._inst.timeout == 5000


def test_last_acw_result_reports_the_testers_own_token():
    class ArcTransport(FakeTransport):
        async def query(self, cmd):
            if cmd == "FETCh?":
                self.log.append(("q", cmd))
                n = sum(1 for k, c in self.log if c == "FETCh?")
                return "1,AC,1.000,0.340" if n == 1 else "1,AC,1.000,0.340,ARC"
            return await super().query(cmd)

    d = Ut5320r("hipot", simulated=True)
    d.simulated = False
    d.transport = ArcTransport()
    assert _run(d.last_acw_result()) == ""                        # nothing measured yet
    leak, brk = _run(d.measure_acw(1500, 3.0, 1))
    assert (leak, brk) == (0.34, True)                            # low mA, still a breakdown ...
    assert _run(d.last_acw_result()) == "ARC"                     # ... and now we can say which


def test_over_range_short_is_a_clean_breakdown_not_a_parse_crash():
    """Seen live (2026-10): on a SHORT the leakage rails past full scale and the tester reports the
    current as ">20.0". float(">20.0") used to raise -> GarbageResponse, so a genuine SHORT was
    MISLABELLED as a tester error BEFORE the SHORT token was read. Now the comparator is stripped:
    numeric boundary reading + the SHORT token flows through as a breakdown FAIL."""
    class OverRangeShort(FakeTransport):
        async def query(self, cmd):
            if cmd == "FETCh?":
                self.log.append(("q", cmd))
                n = sum(1 for k, c in self.log if c == "FETCh?")
                return "1,AC,0.000,0.000" if n == 1 else "1,AC,0.000,>20.0,SHORT"
            return await super().query(cmd)

    d = Ut5320r("hipot", simulated=True)
    d.simulated = False
    d.transport = OverRangeShort()
    leak, brk = _run(d.measure_acw(2500, 5.0, 1, current_limit_ma=10.0))
    assert (leak, brk) == (20.0, True)                            # boundary magnitude, breakdown=True
    assert _run(d.last_acw_result()) == "SHORT"

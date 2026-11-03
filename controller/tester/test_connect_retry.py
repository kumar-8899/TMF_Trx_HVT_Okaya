"""connect_all bootup retry: an instrument that is not answering yet at software start (a safety
tester can need tens of seconds after power-on before it responds to VISA, and does not even ping
until then) must NOT be given up on. connect_all connects once, then retries the stragglers in the
background at a fixed interval until they come up — the controller boots immediately and the UI's
run-start gate clears the moment the instrument reports connected."""

import time

from controller.instruments.registry import InstrumentRegistry
from controller.loop import AsyncLoopThread


class SlowInst:
    """A real (non-simulated) instrument that refuses `connect()` the first `fail_times` times
    (link not up yet), then connects. Enough surface for the registry's retry loop."""
    CONNECTED = "connected"

    def __init__(self, iid, *, fail_times, simulated=False):
        self.instance_id = iid
        self.simulated = simulated
        self.state = "disconnected"
        self._fail = fail_times
        self.connect_calls = 0

    async def connect(self):
        self.connect_calls += 1
        if self._fail > 0:
            self._fail -= 1
            self.state = "disconnected"
            raise RuntimeError("instrument not answering yet")
        self.state = self.CONNECTED

    async def disconnect(self):
        self.state = "disconnected"


def _wait_until(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_a_slow_instrument_is_retried_in_the_background_until_it_connects():
    loop = AsyncLoopThread(); loop.start()
    reg = InstrumentRegistry(loop)
    inst = SlowInst("hv", fail_times=2)
    reg._by_id["hv"] = inst
    try:
        loop.run(reg.connect_all(retry_interval_s=0.05))   # first attempt fails -> background retry
        assert "hv" in reg._connect_retries                 # a retry task was scheduled
        assert _wait_until(lambda: inst.state == inst.CONNECTED)
        assert inst.connect_calls >= 3                       # 1 initial + >=2 retries
    finally:
        loop.run(reg.disconnect_all())
        loop.stop()


def test_disconnect_all_cancels_a_pending_retry():
    loop = AsyncLoopThread(); loop.start()
    reg = InstrumentRegistry(loop)
    inst = SlowInst("hv", fail_times=999)                    # never comes up on its own
    reg._by_id["hv"] = inst
    try:
        loop.run(reg.connect_all(retry_interval_s=0.05))
        assert _wait_until(lambda: inst.connect_calls >= 2)  # retry loop is running
        loop.run(reg.disconnect_all())
        assert reg._connect_retries == {}                    # cancelled + cleared
    finally:
        loop.stop()


def test_a_simulated_instrument_is_not_retried():
    """A simulated instance never has real hardware behind it; if it somehow fails to connect
    that is a bug to surface, not a link to wait on — so no background retry is scheduled."""
    loop = AsyncLoopThread(); loop.start()
    reg = InstrumentRegistry(loop)
    inst = SlowInst("sim", fail_times=1, simulated=True)
    reg._by_id["sim"] = inst
    try:
        loop.run(reg.connect_all(retry_interval_s=0.05))
        assert reg._connect_retries == {}                    # simulated -> no retry task
    finally:
        loop.run(reg.disconnect_all())
        loop.stop()

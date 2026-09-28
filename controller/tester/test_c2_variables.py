"""C2 — variable engine (scale/clamp/direction) + instrument registry, broker-free."""

import pytest

from controller.instruments.registry import InstrumentRegistry, RegistryError
from controller.instruments.variables import StationVariables, VariableError
from controller.loop import AsyncLoopThread
from tester import _fakelib


@pytest.fixture(scope="module")
def loop():
    lt = AsyncLoopThread()
    lt.start()
    yield lt
    lt.stop()


# ---- variable engine (fake registry, no instrumentlib) --------------------

class _FakeInst:
    def __init__(self):
        self.calls = []

    async def invoke(self, method, *args):
        self.calls.append((method, args))
        return 5.0 if method.startswith("measure") else None


class _FakeReg:
    def __init__(self, inst):
        self._inst = inst

    def require(self, _id):
        return self._inst


def _vars(loop, signals):
    inst = _FakeInst()
    return StationVariables("st1", {"signals": signals, "actions": {}}, _FakeReg(inst), loop), inst


def test_read_applies_gain_offset(loop):
    v, _ = _vars(loop, {"vbus": {"instance": "p", "read": "measure_voltage",
                                 "scale": {"gain": 2.0, "offset": 1.0}, "units": "V"}})
    r = v.read("vbus")
    assert r["raw"] == 5.0 and r["value"] == 11.0 and r["units"] == "V"


def test_write_clamps_and_inverse_scales(loop):
    v, inst = _vars(loop, {"vbus": {"instance": "p", "write": "set_voltage",
                                    "scale": {"gain": 2.0, "offset": 0.0},
                                    "clamp": {"min": 0.0, "max": 30.0}}})
    r = v.write("vbus", 100.0)
    assert r["written"] == 30.0 and r["clamped"] is True
    assert inst.calls[-1] == ("set_voltage", (15.0,))     # (30 - 0) / 2


def test_unknown_signal_raises(loop):
    v, _ = _vars(loop, {})
    with pytest.raises(VariableError):
        v.read("nope")


def test_direction_enforced(loop):
    v, _ = _vars(loop, {"ro": {"instance": "p", "read": "measure_voltage"}})
    with pytest.raises(VariableError):
        v.write("ro", 1.0)


# ---- instrument registry (real instrumentlib, hermetic fake lib) ----------

def test_registry_builds_connects_and_guards_double_open(loop):
    lib = _fakelib.ensure_registered()
    reg = InstrumentRegistry(loop)
    reg.build([{"id": "psu1", "library": lib, "simulated": True, "params": {"resource": "A"}}])
    loop.run(reg.connect_all())
    assert reg.require("psu1").state == "connected"
    assert reg.status()[0]["state"] == "connected"
    # same library + same params resolves to the same device -> refused
    with pytest.raises(RegistryError):
        reg.build([{"id": "psu2", "library": lib, "simulated": True, "params": {"resource": "A"}}])


def test_registry_skips_unknown_library(loop):
    reg = InstrumentRegistry(loop)
    reg.build([{"id": "x", "library": "nope_not_registered", "simulated": True}])
    assert reg.get("x") is None
    assert reg.skipped and reg.skipped[0]["library"] == "nope_not_registered"


def test_registry_skips_instrument_that_fails_to_construct(loop):
    """Issue 6 (framework-fix-prompt.md): one instrument raising in __init__ must not take
    the whole registry (and therefore the whole controller process) down with it — the
    healthy instrument must still be built, and the faulty one must land in `skipped` with
    a useful reason instead of propagating."""
    good_lib = _fakelib.ensure_registered()
    bad_lib = _fakelib.ensure_bad_registered()
    reg = InstrumentRegistry(loop)
    reg.build([
        {"id": "good1", "library": good_lib, "simulated": True, "params": {"resource": "B"}},
        # simulated=False on a driver that raises when not simulated (the real-hardware
        # guard shape from the downstream bench) -- must be skipped, not fatal.
        {"id": "bad1", "library": bad_lib, "simulated": False, "params": {"resource": "C"}},
    ])
    assert reg.require("good1") is not None
    assert reg.get("bad1") is None
    assert reg.skipped and reg.skipped[0]["id"] == "bad1"
    assert "NotImplementedError" in reg.skipped[0]["reason"] or "not wired" in reg.skipped[0]["reason"]
    # surfaced distinctly in status(), not just absent (the other half of Issue 6)
    statuses = {s["id"]: s for s in reg.status()}
    assert statuses["good1"]["state"] != "skipped"
    assert statuses["bad1"]["state"] == "skipped"
    assert statuses["bad1"]["reason"]


def test_registry_construct_failure_does_not_block_connect_all(loop):
    """Regression-guards the actual downstream symptom: a mixed healthy/faulty config must
    still let connect_all() bring up the healthy instrument."""
    good_lib = _fakelib.ensure_registered()
    bad_lib = _fakelib.ensure_bad_registered()
    reg = InstrumentRegistry(loop)
    reg.build([
        {"id": "good2", "library": good_lib, "simulated": True, "params": {"resource": "D"}},
        {"id": "bad2", "library": bad_lib, "simulated": False, "params": {"resource": "E"}},
    ])
    loop.run(reg.connect_all())
    assert reg.require("good2").state == "connected"

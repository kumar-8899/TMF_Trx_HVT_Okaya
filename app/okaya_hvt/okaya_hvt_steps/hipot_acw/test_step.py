"""hipot_acw handler tests — a lightweight StepContext double (no instrument registry, no
event loop). Scripts what `ctx.invoke(action, "measure_acw", ...)` returns/raises and records
relay writes so each scenario can assert the route is always closed, then always opened again,
regardless of how the step ends (§7.3 rule 7 / r3 safety).

Behavioural numbers here are test-harness sentinels, not a product spec: this step type's
pass/fail is entirely parametrised (`max_current_ma` from the recipe), so there is no fixed
DUT constant to get wrong — what's under test is the routing/limit-judgement/safety logic,
which the framework's own `Limits`/`Measurement` evaluation (exercised via `results.finalize`)
already owns.
"""

from __future__ import annotations

import pytest

from controller.context import StepAborted
from controller.results import FAIL, PASS, finalize
from okaya_hvt_steps.hipot_acw.handler import HipotAcw

_PARAMS = {
    "route": ["hipot_route_pri_sec"],
    "voltage": 1500.0,
    "test_time": 3.0,
    "max_current_ma": 5.0,
}


class FakeCtx:
    """Records writes/waits; returns or raises whatever the test scripts for invoke()."""

    def __init__(self, invoke_result=None, invoke_error=None, wait_error=None):
        self.writes: list[tuple[str, float]] = []
        self.waited: list[float] = []
        self.invoked_with = None
        self._invoke_result = invoke_result
        self._invoke_error = invoke_error
        self._wait_error = wait_error

    def write(self, name, value):
        self.writes.append((name, value))
        return value

    def wait(self, seconds):
        self.waited.append(seconds)
        if self._wait_error is not None:
            raise self._wait_error

    def invoke(self, action, method, args=None):
        self.invoked_with = (action, method, args)
        if self._invoke_error is not None:
            raise self._invoke_error
        return self._invoke_result


def _route_states(ctx):
    """The sequence of (signal, value) writes, in order — proves close-then-open."""
    return ctx.writes


# ---- nominal DUT ------------------------------------------------------------

def test_nominal_dut_passes_and_route_closes_then_opens():
    ctx = FakeCtx(invoke_result=(1.2, False))
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)

    leakage, breakdown = result.measurements
    assert leakage.value == 1.2 and leakage.status == PASS
    assert breakdown.value is False and breakdown.status == PASS
    assert ctx.invoked_with == ("hipot", "measure_acw", [1500.0, 3.0, 1])
    assert _route_states(ctx) == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]


# ---- out-of-limit DUT (excess leakage, no breakdown) ------------------------

def test_excess_leakage_fails_on_the_leakage_measurement_only():
    ctx = FakeCtx(invoke_result=(8.0, False))
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)

    leakage, breakdown = result.measurements
    assert leakage.status == FAIL          # 8.0 > max_current_ma (5.0)
    assert breakdown.status == PASS        # no dielectric fault reported
    assert _route_states(ctx)[-1] == ("hipot_route_pri_sec", 0)


# ---- dielectric breakdown (a second, distinct bad-DUT failure mode) --------

def test_breakdown_fails_even_when_leakage_reads_within_limits():
    ctx = FakeCtx(invoke_result=(2.0, True))
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)

    leakage, breakdown = result.measurements
    assert leakage.status == PASS          # 2.0 <= max_current_ma — reads fine on its own
    assert breakdown.status == FAIL        # but the tester reported a genuine breakdown
    assert _route_states(ctx)[-1] == ("hipot_route_pri_sec", 0)


# ---- boundary: leakage exactly at the limit --------------------------------

def test_leakage_exactly_at_max_current_passes():
    ctx = FakeCtx(invoke_result=(5.0, False))
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)
    assert result.measurements[0].status == PASS   # inclusive: x <= max passes


# ---- non-responsive / faulted tester ---------------------------------------

def test_tester_error_propagates_and_route_still_opens():
    ctx = FakeCtx(invoke_error=RuntimeError("tester link dropped"))
    with pytest.raises(RuntimeError):
        HipotAcw().execute(_PARAMS, ctx)
    assert _route_states(ctx) == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]


# ---- aborted mid-step (before the tester is ever invoked) ------------------

def test_abort_during_settle_still_opens_the_route_and_never_invokes():
    ctx = FakeCtx(wait_error=StepAborted())
    with pytest.raises(StepAborted):
        HipotAcw().execute(_PARAMS, ctx)
    assert ctx.invoked_with is None
    assert _route_states(ctx) == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]


# ---- multi-relay route + custom name/step ----------------------------------

def test_multi_relay_route_and_custom_name_step():
    ctx = FakeCtx(invoke_result=(0.3, False))
    params = {**_PARAMS, "route": ["hipot_route_pri_core", "hipot_route_sec_core"],
             "name": "pri_core_leakage", "step": 2}
    result = HipotAcw().execute(params, ctx)

    assert ctx.invoked_with == ("hipot", "measure_acw", [1500.0, 3.0, 2])
    assert [n for n, _ in ctx.writes[:2]] == ["hipot_route_pri_core", "hipot_route_sec_core"]
    assert [n for n, _ in ctx.writes[2:]] == ["hipot_route_pri_core", "hipot_route_sec_core"]
    names = [m.name for m in result.measurements]
    assert names == ["pri_core_leakage", "pri_core_leakage_breakdown"]


def test_bindings_declare_the_route_signals_and_action():
    b = HipotAcw.bindings({**_PARAMS, "action": "hipot"})
    assert b == {"signals": ["hipot_route_pri_sec"], "actions": ["hipot"]}

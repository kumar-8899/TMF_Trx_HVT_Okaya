"""hipot_acw handler tests — a lightweight StepContext double (no instrument registry, no
event loop). Scripts what `ctx.invoke(action, "measure_acw", ...)` returns/raises and records
relay writes so each scenario can assert the route is always closed, then always opened again,
regardless of how the step ends (§7.3 rule 7 / r3 safety).

Contract: ONE measurement row per run, and a failed test is always a visible FAIL row — over-limit
leakage, a reported breakdown, and a tester/link error all return a row instead of raising. Only
an operator abort (StepAborted) propagates. The last section drives the REAL sequencer with a
recipe shaped like the recipe form's output, to prove the Results table gets every row and that
`stop_on_fail` skips only the tests AFTER the first failure.

Behavioural numbers here are test-harness sentinels, not a product spec: this step type's
pass/fail is entirely parametrised (`max_current_ma` from the recipe), so there is no fixed
DUT constant to get wrong — what's under test is the routing/limit-judgement/safety logic,
which the framework's own `Limits`/`Measurement` evaluation (exercised via `results.finalize`)
already owns.
"""

from __future__ import annotations

import time

import pytest

import controller.step_types  # noqa: F401 — registers the core types (group)
from controller.context import StepAborted
from controller.results import FAIL, PASS, finalize
from controller.sequencer import Sequencer
from okaya_hvt_steps.hipot_acw.handler import HipotAcw

_PARAMS = {
    "route": ["hipot_route_pri_sec"],
    "voltage": 1500.0,
    "test_time": 3.0,
    "max_current_ma": 5.0,
}


class FakeCtx:
    """Records writes/waits/diags; returns or raises whatever the test scripts for invoke()."""

    def __init__(self, invoke_result=None, invoke_error=None, wait_error=None):
        self.writes: list[tuple[str, float]] = []
        self.waited: list[float] = []
        self.diags: list[tuple[str, str, dict]] = []
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

    def diag(self, level, message, **fields):
        self.diags.append((level, message, fields))


def _route_states(ctx):
    """The sequence of (signal, value) writes, in order — proves close-then-open."""
    return ctx.writes


# ---- nominal DUT ------------------------------------------------------------

def test_nominal_dut_passes_and_route_closes_then_opens():
    ctx = FakeCtx(invoke_result=(1.2, False))
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)

    (leakage,) = result.measurements              # exactly one row
    assert leakage.name == "leakage_current"      # default name
    assert leakage.value == 1.2 and leakage.unit == "mA" and leakage.status == PASS
    assert ctx.invoked_with == ("hipot", "measure_acw", [1500.0, 3.0, 1, 5.0])
    assert _route_states(ctx) == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]


# ---- out-of-limit DUT (excess leakage, no breakdown) ------------------------

def test_excess_leakage_fails_and_shows_the_reading():
    ctx = FakeCtx(invoke_result=(8.0, False))
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)

    (leakage,) = result.measurements
    assert leakage.value == 8.0 and leakage.status == FAIL     # 8.0 > max_current_ma (5.0)
    assert _route_states(ctx)[-1] == ("hipot_route_pri_sec", 0)


# ---- dielectric breakdown: still a hard FAIL, and now a VISIBLE one ---------

def test_breakdown_fails_even_when_leakage_reads_within_limits():
    ctx = FakeCtx(invoke_result=(2.0, True))
    result = HipotAcw().execute(_PARAMS, ctx)          # must NOT raise
    finalize(result.measurements)

    (leakage,) = result.measurements
    assert leakage.value == 2.0                        # the reading is shown ...
    assert leakage.status == FAIL                      # ... and 2.0 <= 5.0 can't mask the breakdown
    assert "breakdown" in result.message
    assert _route_states(ctx)[-1] == ("hipot_route_pri_sec", 0)


# ---- boundary: leakage exactly at the limit --------------------------------

def test_leakage_exactly_at_max_current_passes():
    ctx = FakeCtx(invoke_result=(5.0, False))
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)
    assert result.measurements[0].status == PASS   # inclusive: x <= max passes


# ---- non-responsive / faulted tester: a FAIL row, not a missing one ----------

def test_tester_error_returns_a_fail_row_and_route_still_opens():
    ctx = FakeCtx(invoke_error=RuntimeError("tester link dropped"))
    result = HipotAcw().execute(_PARAMS, ctx)          # must NOT raise
    finalize(result.measurements)

    (row,) = result.measurements
    assert row.value == "ERROR" and row.status == FAIL  # non-numeric vs numeric limits = FAIL
    assert "tester link dropped" in result.message and "RuntimeError" in result.message
    assert _route_states(ctx) == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]
    assert any(msg == "hipot_acw.measure_failed" and lvl == "error" for lvl, msg, _ in ctx.diags)


def test_tester_error_still_holds_the_route_closed_for_the_full_dwell_margin():
    # the tester may still be applying HV when the call fails — never hot-switch the relays
    ctx = FakeCtx(invoke_error=RuntimeError("timeout"))
    HipotAcw().execute({**_PARAMS, "test_time": 3.0, "off_margin_s": 4.0}, ctx)
    # waits: settle_s, the floor (~7 s minus the instant the failed call took), settle_off_s
    assert len(ctx.waited) == 3 and 6.0 < ctx.waited[1] <= 7.0


def test_malformed_reply_is_a_fail_row_too():
    ctx = FakeCtx(invoke_result=None)                  # driver returned garbage, not (mA, flag)
    result = HipotAcw().execute(_PARAMS, ctx)
    finalize(result.measurements)
    assert result.measurements[0].status == FAIL and result.measurements[0].value == "ERROR"
    assert _route_states(ctx)[-1] == ("hipot_route_pri_sec", 0)


# ---- aborted: the one thing that must still propagate -----------------------

def test_abort_during_settle_still_opens_the_route_and_never_invokes():
    ctx = FakeCtx(wait_error=StepAborted())
    with pytest.raises(StepAborted):
        HipotAcw().execute(_PARAMS, ctx)
    assert ctx.invoked_with is None
    assert _route_states(ctx) == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]


def test_abort_raised_by_the_tester_call_is_not_swallowed_into_a_fail_row():
    ctx = FakeCtx(invoke_error=StepAborted())
    with pytest.raises(StepAborted):
        HipotAcw().execute(_PARAMS, ctx)
    assert _route_states(ctx) == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]


# ---- multi-relay route + custom name/step ----------------------------------

def test_multi_relay_route_and_custom_name_step():
    ctx = FakeCtx(invoke_result=(0.3, False))
    params = {**_PARAMS, "route": ["hipot_route_pri_core", "hipot_route_sec_core"],
             "name": "pri_core_leakage", "step": 2}
    result = HipotAcw().execute(params, ctx)

    assert ctx.invoked_with == ("hipot", "measure_acw", [1500.0, 3.0, 2, 5.0])
    assert [n for n, _ in ctx.writes[:2]] == ["hipot_route_pri_core", "hipot_route_sec_core"]
    assert [n for n, _ in ctx.writes[2:]] == ["hipot_route_pri_core", "hipot_route_sec_core"]
    assert [m.name for m in result.measurements] == ["pri_core_leakage"]


def test_a_human_readable_name_passes_through_unchanged():
    ctx = FakeCtx(invoke_result=(0.3, False))
    result = HipotAcw().execute({**_PARAMS, "name": "Primary to Secondary"}, ctx)
    assert result.measurements[0].name == "Primary to Secondary"


def test_bindings_declare_the_route_signals_and_action():
    b = HipotAcw.bindings({**_PARAMS, "action": "hipot"})
    assert b == {"signals": ["hipot_route_pri_sec"], "actions": ["hipot"]}


# ---- end to end through the REAL sequencer ----------------------------------
# A recipe shaped exactly like HipotRecipeForm.buildSteps() output: one group per test point,
# each wrapping one hipot_acw step whose `name` is the human label. No sleeping: every settle /
# dwell param is 0.

_FAST = {"voltage": 1500.0, "test_time": 0.0, "max_current_ma": 5.0,
         "settle_s": 0.0, "settle_off_s": 0.0, "off_margin_s": 0.0}
_LABELS = {"pri_sec": "Primary to Secondary", "pri_core": "Primary to Core",
           "sec_core": "Secondary to Core"}


class _Vars:
    """Scripted variable engine: one reply (a (mA, breakdown) tuple, or an Exception to raise)
    per hipot call, in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.writes: list[tuple[str, float]] = []

    def read(self, name):
        return {"value": 0.0}

    def write(self, name, value):
        self.writes.append((name, value))
        return {"written": value}

    def invoke(self, action, method, args=None):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _recipe(*keys, stop_on_fail=None):
    groups = [{"type": "group", "id": k, "params": {"name": _LABELS[k], "steps": [
        {"type": "hipot_acw", "id": f"{k}_hipot",
         "params": {**_FAST, "route": [f"hipot_route_{k}"], "name": _LABELS[k]}}]}}
        for k in keys]
    recipe = {"steps": groups}
    if stop_on_fail is not None:
        recipe["stop_on_fail"] = stop_on_fail
    return recipe


def _run(recipe, replies):
    events, vars_ = [], _Vars(replies)
    verdict = Sequencer(vars_, lambda t, p: events.append((t, p)), lambda *a, **k: None).run(
        recipe, run_id="r1", station="st1", run_parameters={},
        deadline_ts=time.monotonic() + 10, aborted_fn=lambda: False)
    rows = [(p["test_name"], p["measured"], p["result"]) for t, p in events if t == "test-result"]
    return verdict, rows, vars_


def test_results_table_gets_human_names_for_every_test():
    verdict, rows, _ = _run(_recipe("pri_sec", "pri_core"), [(1.0, False), (2.0, False)])
    assert verdict == PASS
    assert rows == [("Primary to Secondary", 1.0, PASS), ("Primary to Core", 2.0, PASS)]


def test_a_failed_test_is_always_listed_and_the_run_continues_by_default():
    # OFF (default): breakdown on test 1, tester error on test 2, clean test 3 -> three rows
    verdict, rows, _ = _run(_recipe("pri_sec", "pri_core", "sec_core"),
                            [(2.0, True), RuntimeError("link dropped"), (1.0, False)])
    assert verdict == FAIL
    assert rows == [("Primary to Secondary", 2.0, FAIL),
                    ("Primary to Core", "ERROR", FAIL),
                    ("Secondary to Core", 1.0, PASS)]


def test_stop_on_fail_stops_after_the_first_failed_test_and_still_lists_it():
    verdict, rows, vars_ = _run(_recipe("pri_sec", "pri_core", "sec_core", stop_on_fail=True),
                                [(1.0, False), (9.0, False), (1.0, False)])
    assert verdict == FAIL
    assert rows == [("Primary to Secondary", 1.0, PASS), ("Primary to Core", 9.0, FAIL)]
    assert vars_.replies == [(1.0, False)]                      # test 3's tester call never made
    assert ("hipot_route_sec_core", 1) not in vars_.writes      # its relay never energised


def test_stop_on_fail_also_stops_after_a_tester_error_and_lists_it():
    verdict, rows, vars_ = _run(_recipe("pri_sec", "pri_core", stop_on_fail=True),
                                [RuntimeError("link dropped"), (1.0, False)])
    assert verdict == FAIL
    assert rows == [("Primary to Secondary", "ERROR", FAIL)]
    assert vars_.writes == [("hipot_route_pri_sec", 1), ("hipot_route_pri_sec", 0)]  # route reopened

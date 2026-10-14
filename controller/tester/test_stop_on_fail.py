"""D2 — recipe-level `stop_on_fail` (RECIPE.md §2, PYTHON_CONTROLLER.md).

When strictly `true`, the top-level walk stops after the FIRST top-level step whose final
attempt FAILs: the remaining top-level steps are skipped (no step-started/-completed/test-result,
one `step.skipped` diag each), the failing step's own row is still emitted, and the verdict is
FAIL. Any other value (absent / false / "true" / 1) keeps the historic always-continue behaviour.
Teardown is owned by runstate.py and is unaffected by this flag.
"""

import time

import controller.step_types  # noqa: F401 — registers the 8 core types
from controller.results import FAIL, PASS
from controller.sequencer import Sequencer


class _Vars:
    def __init__(self, values=None):
        self.signals = dict(values or {})

    def read(self, name):
        return {"value": self.signals.get(name, 0.0)}

    def write(self, name, value):
        self.signals[name] = value
        return {"written": value}


def _run(recipe, vars=None):
    vars = vars or _Vars()
    events, diags = [], []
    seq = Sequencer(vars, lambda t, p: events.append((t, p)),
                    lambda level, msg, **f: diags.append((level, msg, f)))
    result = seq.run(recipe, run_id="r1", station="st1", run_parameters={},
                     deadline_ts=time.monotonic() + 10, aborted_fn=lambda: False)
    return result, events, diags


_FAIL_STEP = {"type": "measure_and_compare", "id": "bad", "params": {"signal": "v", "min": 100}}
_PASS_STEP = {"type": "measure_and_compare", "id": "ok", "params": {"signal": "v", "max": 100}}


def test_stop_on_fail_skips_subsequent_steps():
    r, ev, diags = _run(
        {"stop_on_fail": True,
         "steps": [_FAIL_STEP, _PASS_STEP, {"type": "wait", "id": "w", "params": {"seconds": 0}}]},
        _Vars({"v": 5}))
    assert r == FAIL
    started = [p["step_id"] for t, p in ev if t == "step-started"]
    assert started == ["bad"]                       # only the failing step ran
    trs = [p for t, p in ev if t == "test-result"]
    assert len(trs) == 1 and trs[0]["result"] == FAIL   # the failing step's own row is still emitted
    skipped = [f["step_id"] for lvl, msg, f in diags if msg == "step.skipped"]
    assert skipped == ["ok", "w"]                   # one step.skipped diag per skipped step


def test_absent_stop_on_fail_continues():
    r, ev, diags = _run({"steps": [_FAIL_STEP, _PASS_STEP]}, _Vars({"v": 5}))
    assert r == FAIL
    assert [p["step_id"] for t, p in ev if t == "step-started"] == ["bad", "ok"]
    assert not [1 for lvl, msg, f in diags if msg == "step.skipped"]


def test_only_strict_true_stops():
    for val in ("true", 1, "yes", False):
        _, ev, _ = _run({"stop_on_fail": val, "steps": [_FAIL_STEP, _PASS_STEP]}, _Vars({"v": 5}))
        started = [p["step_id"] for t, p in ev if t == "step-started"]
        assert started == ["bad", "ok"], f"stop_on_fail={val!r} must not stop"


def test_stop_on_fail_all_pass_runs_everything():
    r, ev, _ = _run({"stop_on_fail": True, "steps": [_PASS_STEP, _PASS_STEP]}, _Vars({"v": 5}))
    assert r == PASS
    assert len([1 for t, p in ev if t == "step-started"]) == 2

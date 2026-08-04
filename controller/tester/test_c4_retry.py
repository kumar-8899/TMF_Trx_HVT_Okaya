"""C4 — retry semantics (PYTHON_CONTROLLER.md §6.1). step-started/completed per attempt;
test-result only on the final attempt; a retried-then-passed step is a PASS at attempt N
and does not poison the run verdict; a step failing every attempt fails once, at the end."""

import time

import controller.step_types  # noqa: F401 — registers the 8 core types
from controller.results import FAIL, PASS
from controller.sequencer import Sequencer


class _CountingVars:
    """read(name) returns an incrementing counter — the Nth read yields N. Models flaky
    instrumentation that settles: attempt 1 reads 1, attempt 2 reads 2, …"""
    def __init__(self):
        self.n = 0

    def read(self, name):
        self.n += 1
        return {"value": float(self.n)}

    def write(self, name, value):
        return {"written": value}


def _run(recipe, vars):
    events = []
    seq = Sequencer(vars, lambda t, p: events.append((t, p)), lambda *a, **k: None)
    result = seq.run(recipe, run_id="r", station="st1", run_parameters={},
                     deadline_ts=time.monotonic() + 10, aborted_fn=lambda: False)
    return result, events


def test_passes_on_second_attempt():
    # needs value >= 2; attempt 1 reads 1 (FAIL), attempt 2 reads 2 (PASS)
    recipe = {"steps": [{"type": "measure_and_compare", "id": "m", "retry_count": 2,
                         "params": {"signal": "v", "min": 2}}]}
    result, ev = _run(recipe, _CountingVars())
    assert result == PASS                                   # retry rescued it
    started = [p for t, p in ev if t == "step-started"]
    completed = [p for t, p in ev if t == "step-completed"]
    trs = [p for t, p in ev if t == "test-result"]
    assert [p["attempt"] for p in started] == [1, 2]        # per-attempt
    assert [p["status"] for p in completed] == [FAIL, PASS]
    assert all(p["attempts_allowed"] == 3 for p in completed)
    assert len(trs) == 1 and trs[0]["attempt"] == 2 and trs[0]["result"] == PASS  # final only


def test_fails_all_attempts():
    # value never reaches 100; every attempt FAILs, one test-result at the end, run FAIL
    recipe = {"steps": [{"type": "measure_and_compare", "id": "m", "retry_count": 2,
                         "params": {"signal": "v", "min": 100}}]}
    result, ev = _run(recipe, _CountingVars())
    assert result == FAIL
    started = [p for t, p in ev if t == "step-started"]
    trs = [p for t, p in ev if t == "test-result"]
    assert len(started) == 3                                 # attempts_allowed
    assert len(trs) == 1 and trs[0]["attempt"] == 3 and trs[0]["result"] == FAIL


def test_no_retry_by_default():
    recipe = {"steps": [{"type": "measure_and_compare", "id": "m",
                         "params": {"signal": "v", "min": 100}}]}
    result, ev = _run(recipe, _CountingVars())
    assert result == FAIL
    assert len([p for t, p in ev if t == "step-started"]) == 1
    assert all(p["attempts_allowed"] == 1 for t, p in ev if t == "step-completed")


def test_pass_first_attempt_no_extra_attempts():
    recipe = {"steps": [{"type": "measure_and_compare", "id": "m", "retry_count": 5,
                         "params": {"signal": "v", "min": 0}}]}       # attempt 1 reads 1 -> PASS
    result, ev = _run(recipe, _CountingVars())
    assert result == PASS
    assert len([p for t, p in ev if t == "step-started"]) == 1        # stopped at first PASS

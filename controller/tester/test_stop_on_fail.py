"""Recipe-level `stop_on_fail` (PYTHON_CONTROLLER.md §6). Headless: fake variable engine +
event collector, no broker, no hardware.

Contract under test: default (key absent / false) runs every step regardless of earlier
failures; `stop_on_fail: true` skips every step AFTER the first one whose FINAL attempt FAILed.
A skipped step emits no step-started/step-completed/test-result, the failing step's own
test-result row is still emitted, the run verdict is FAIL, and teardown still runs."""

import time

import controller.step_types  # noqa: F401 — registers the 8 core types
from controller.results import FAIL, PASS
from controller.runstate import IDLE, RunEngine
from controller.sequencer import Sequencer


class _Vars:
    """`good` reads 5 (inside 0..10), `bad` reads 99 (outside 0..10)."""

    def __init__(self):
        self.signals = {"good": 5.0, "bad": 99.0}

    def read(self, name):
        return {"value": self.signals[name]}

    def write(self, name, value):
        return {"written": value}


class _CountingVars:
    """The Nth read returns N — models a flaky instrument that settles on a later attempt."""

    def __init__(self):
        self.n = 0

    def read(self, name):
        self.n += 1
        return {"value": float(self.n)}

    def write(self, name, value):
        return {"written": value}


def _ok(step_id, **extra):
    return {"type": "measure_and_compare", "id": step_id,
            "params": {"signal": "good", "min": 0, "max": 10}, **extra}


def _bad(step_id, **extra):
    return {"type": "measure_and_compare", "id": step_id,
            "params": {"signal": "bad", "min": 0, "max": 10}, **extra}


def _run(recipe, variables=None):
    events, diags = [], []
    seq = Sequencer(variables or _Vars(), lambda t, p: events.append((t, p)),
                    lambda level, msg, **f: diags.append((level, msg, f)))
    verdict = seq.run(recipe, run_id="r1", station="st1", run_parameters={},
                      deadline_ts=time.monotonic() + 10, aborted_fn=lambda: False)
    return verdict, events, diags


def _started(events):
    return [p["step_id"] for t, p in events if t == "step-started"]


def _result_rows(events):
    return [(p["step_id"], p["result"]) for t, p in events if t == "test-result"]


# ---- default: unchanged behaviour ------------------------------------------

def test_default_runs_every_step_after_a_failure():
    verdict, ev, _ = _run({"steps": [_ok("a"), _bad("b"), _ok("c")]})
    assert verdict == FAIL
    assert _started(ev) == ["a", "b", "c"]
    assert _result_rows(ev) == [("a", PASS), ("b", FAIL), ("c", PASS)]


def test_explicit_false_also_runs_everything():
    verdict, ev, _ = _run({"stop_on_fail": False, "steps": [_bad("a"), _ok("b")]})
    assert verdict == FAIL
    assert _started(ev) == ["a", "b"]


def test_non_boolean_value_does_not_enable_stop():
    # strictly `true` — a stray "true" string / 1 must never silently change a recipe's behaviour
    for bogus in ("true", 1, "yes"):
        _, ev, _ = _run({"stop_on_fail": bogus, "steps": [_bad("a"), _ok("b")]})
        assert _started(ev) == ["a", "b"], bogus


def test_all_passing_recipe_is_unaffected_by_the_flag():
    verdict, ev, _ = _run({"stop_on_fail": True, "steps": [_ok("a"), _ok("b"), _ok("c")]})
    assert verdict == PASS
    assert _started(ev) == ["a", "b", "c"]


# ---- stop_on_fail: true -----------------------------------------------------

def test_stop_on_fail_skips_everything_after_the_first_failure():
    verdict, ev, diags = _run({"stop_on_fail": True,
                               "steps": [_ok("a"), _bad("b"), _ok("c"), _ok("d")]})
    assert verdict == FAIL
    assert _started(ev) == ["a", "b"]                        # c, d never started
    assert [p["step_id"] for t, p in ev if t == "step-completed"] == ["a", "b"]
    skipped = [f["step_id"] for lvl, msg, f in diags if msg == "step.skipped"]
    assert skipped == ["c", "d"]                             # but it is logged, not silent


def test_the_failing_step_still_reports_its_result_row():
    # "a failed test must always be shown": stopping must never swallow the failure itself.
    _, ev, _ = _run({"stop_on_fail": True, "steps": [_bad("a"), _ok("b")]})
    assert _result_rows(ev) == [("a", FAIL)]


def test_stop_on_fail_inside_a_group_skips_siblings_and_later_groups():
    recipe = {"stop_on_fail": True, "steps": [
        {"type": "group", "id": "g1", "params": {"steps": [_ok("g1a"), _bad("g1b"), _ok("g1c")]}},
        {"type": "group", "id": "g2", "params": {"steps": [_ok("g2a")]}},
    ]}
    verdict, ev, _ = _run(recipe)
    assert verdict == FAIL
    assert _started(ev) == ["g1", "g1a", "g1b"]              # g1c, and all of g2, skipped
    completed = {p["step_id"]: p["status"] for t, p in ev if t == "step-completed"}
    assert completed == {"g1a": PASS, "g1b": FAIL, "g1": FAIL}


def test_a_skipped_step_never_reads_as_a_pass_to_its_group():
    # group status = worst(child statuses); the skipped sibling must not launder the FAIL
    recipe = {"stop_on_fail": True, "steps": [
        {"type": "group", "id": "g", "params": {"steps": [_bad("x"), _ok("y")]}}]}
    verdict, ev, _ = _run(recipe)
    assert verdict == FAIL
    assert [p["status"] for t, p in ev if t == "step-completed" and p["step_id"] == "g"] == [FAIL]


# ---- interplay with retry (§6.1): only the FINAL attempt counts --------------

def test_a_retry_that_recovers_does_not_trigger_the_stop():
    # needs value >= 2: attempt 1 reads 1 (FAIL), attempt 2 reads 2 (PASS) -> not a failure
    flaky = {"type": "measure_and_compare", "id": "flaky", "retry_count": 2,
             "params": {"signal": "v", "min": 2}}
    after = {"type": "measure_and_compare", "id": "after", "params": {"signal": "v", "min": 0}}
    verdict, ev, _ = _run({"stop_on_fail": True, "steps": [flaky, after]}, _CountingVars())
    assert verdict == PASS
    assert _started(ev) == ["flaky", "flaky", "after"]       # 2 attempts, then the next step ran


def test_exhausted_retries_do_trigger_the_stop():
    never = {"type": "measure_and_compare", "id": "never", "retry_count": 1,
             "params": {"signal": "v", "min": 1000}}
    after = {"type": "measure_and_compare", "id": "after", "params": {"signal": "v", "min": 0}}
    verdict, ev, _ = _run({"stop_on_fail": True, "steps": [never, after]}, _CountingVars())
    assert verdict == FAIL
    assert _started(ev) == ["never", "never"]                # both attempts ran, `after` did not


# ---- run engine: a stopped run still tears down and ends cleanly -------------

def test_stopped_run_tears_down_and_emits_exactly_one_terminal():
    tore, events = [], []
    eng = RunEngine("st1", variables=_Vars(), emit=lambda t, p: events.append((t, p)),
                    recipe_fetch=lambda rid, ver: {"stop_on_fail": True,
                                                   "steps": [_bad("a"), _ok("b")]},
                    safe_state=lambda: tore.append(1), diag=lambda *a, **k: None)
    eng.start({"recipe_id": "demo", "run_id": "r1"})
    eng._thread.join(5)
    assert eng.state == IDLE and tore == [1]                 # teardown ran despite the early stop
    terminal = [(t, p) for t, p in events if t in ("run-finished", "run-aborted")]
    assert len(terminal) == 1 and terminal[0][0] == "run-finished"
    assert terminal[0][1]["result"] == FAIL
    assert _started(events) == ["a"]

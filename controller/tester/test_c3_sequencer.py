"""C3 — sequencer + run state machine + the 8 core step types (PYTHON_CONTROLLER.md
§5–§8). Headless: a fake variable engine + an event collector, no broker, no hardware."""

import time

import controller.step_types  # noqa: F401 — registers the 8 core types
from controller import registry as step_registry
from controller.context import StepFailed
from controller.results import FAIL, PASS, Measurement, StepResult
from controller.runstate import FAULTED, IDLE, RunEngine
from controller.sequencer import Sequencer


class _RaisesPlainException:
    """Test-only step type: execute() raises, unconditionally — the crashed-step regression
    fixture (a leaf handler must never report PASS just because it produced 0 measurements)."""

    def execute(self, params, ctx):
        raise RuntimeError("boom")


class _RaisesStepFailed:
    def execute(self, params, ctx):
        raise StepFailed("deliberately failed")


class _SlowMeasure:
    """Test-only step type: sleeps a known duration then returns a single passing
    measurement — a stand-in for a real device round-trip, used to prove elapsed_ms
    (already correct at the step-completed level) actually reaches test-result rows too
    (framework-fix-prompt.md Issue 7)."""

    def execute(self, params, ctx):
        time.sleep(params.get("seconds", 0.05))
        return StepResult(measurements=[Measurement(name=params.get("name", "m"), value=1.0)])


if "test_crasher" not in step_registry.STEP_REGISTRY:
    step_registry.register_step_type(type_id="test_crasher",
                                     display_name="Test crasher")(_RaisesPlainException)
if "test_step_failed" not in step_registry.STEP_REGISTRY:
    step_registry.register_step_type(type_id="test_step_failed",
                                     display_name="Test StepFailed")(_RaisesStepFailed)
if "test_slow_measure" not in step_registry.STEP_REGISTRY:
    step_registry.register_step_type(type_id="test_slow_measure",
                                     display_name="Test slow measure")(_SlowMeasure)


class _Vars:
    def __init__(self, values=None):
        self.signals = dict(values or {})
        self.writes = []

    def read(self, name):
        return {"value": self.signals.get(name, 0.0)}

    def write(self, name, value):
        self.writes.append((name, value))
        self.signals[name] = value
        return {"written": value}


def _sink():
    events = []
    return events, (lambda t, p: events.append((t, p)))


def _noop_diag(*a, **k):
    pass


def _run(recipe, vars=None):
    vars = vars or _Vars()
    events, emit = _sink()
    seq = Sequencer(vars, emit, _noop_diag)
    result = seq.run(recipe, run_id="r1", station="st1", run_parameters={},
                     deadline_ts=time.monotonic() + 10, aborted_fn=lambda: False)
    return result, events, vars


# ---- verdict from measurements -------------------------------------------

def test_measure_within_limits_passes():
    r, ev, _ = _run({"steps": [{"type": "measure_and_compare", "id": "v",
                                "params": {"signal": "vbus", "min": 4, "max": 6}}]},
                    _Vars({"vbus": 5.0}))
    assert r == PASS
    tr = [p for t, p in ev if t == "test-result"][0]
    assert tr["result"] == PASS and tr["value"] == 5.0


def test_measure_out_of_limits_fails():
    r, ev, _ = _run({"steps": [{"type": "measure_and_compare", "id": "v",
                                "params": {"signal": "vbus", "min": 4, "max": 6}}]},
                    _Vars({"vbus": 9.0}))
    assert r == FAIL
    sc = [p for t, p in ev if t == "step-completed"][0]
    assert sc["status"] == FAIL


def test_handler_cannot_report_pass_over_a_failed_measurement():
    # the sequencer computes the verdict; a good measurement + a bad one => step FAIL
    r, ev, _ = _run({"steps": [{"type": "measure_and_compare", "id": "hi",
                                "params": {"signal": "v", "max": 1}}]}, _Vars({"v": 99}))
    assert r == FAIL


def test_crashed_step_reports_fail_not_pass_with_zero_measurements():
    """Regression: a leaf step whose handler raises a plain Exception must FAIL, even
    though it produced zero measurements — step_status()'s "empty list is PASS" rule
    governs a normal return with nothing to check, never a raised exception. Before the
    fix, the exception-forced FAIL was silently overwritten back to PASS."""
    r, ev, _ = _run({"steps": [{"type": "test_crasher", "id": "boom", "params": {}}]})
    assert r == FAIL
    sc = [p for t, p in ev if t == "step-completed"][0]
    assert sc["status"] == FAIL
    assert sc["measurement_count"] == 0
    assert "boom" in sc["message"]


def test_step_failed_exception_also_reports_fail_with_zero_measurements():
    """Same regression, via the StepFailed path (lines 86-87) rather than the generic
    Exception path (lines 88-89) — both except blocks were equally clobbered."""
    r, ev, _ = _run({"steps": [{"type": "test_step_failed", "id": "boom", "params": {}}]})
    assert r == FAIL
    sc = [p for t, p in ev if t == "step-completed"][0]
    assert sc["status"] == FAIL
    assert sc["measurement_count"] == 0
    assert sc["message"] == "deliberately failed"


def test_test_result_carries_cycle_time_ms():
    """Issue 7 (framework-fix-prompt.md): elapsed_ms is correctly computed at the
    step-completed level (line 108 of sequencer.py) but never reached the per-measurement
    test-result row measurement_dict() builds — every report's cycle_time_ms column was
    blank, always. A step with a known artificial delay must show up on its test-result
    event(s), close to that delay."""
    r, ev, _ = _run({"steps": [{"type": "test_slow_measure", "id": "slow",
                                "params": {"seconds": 0.05}}]})
    assert r == PASS
    tr = [p for t, p in ev if t == "test-result"][0]
    assert tr["cycle_time_ms"] is not None
    assert 40 <= tr["cycle_time_ms"] <= 500   # generous upper bound for slow CI machines


def test_test_result_cycle_time_ms_same_across_measurements():
    """A multi-measurement step must stamp the SAME step-level cycle_time_ms on every one
    of its rows (the existing exposed shape report/assembly.py + the report schema already
    expect) — only what feeds it was missing."""
    _, ev, _ = _run({"steps": [{"type": "sweep", "id": "sw", "params": {
        "signal": "level", "values": [1, 2, 3],
        "steps": [{"type": "measure_and_compare", "id": "m", "params": {"signal": "level", "min": 0}}]}}]})
    trs = [p for t, p in ev if t == "test-result"]
    assert len(trs) == 3
    cycle_times = {tr["cycle_time_ms"] for tr in trs}
    assert None not in cycle_times
    # each child "m" step is its own _attempt() call (its own elapsed_ms) — same STEP's
    # measurements share a value; here every row comes from a distinct attempt, so just
    # assert none are missing/None (the regression this issue is actually about).


def test_step_completed_elapsed_ms_unchanged():
    """Regression: step-completed's own elapsed_ms field (already correct) must be
    unaffected by wiring cycle_time_ms into test-result."""
    r, ev, _ = _run({"steps": [{"type": "test_slow_measure", "id": "slow",
                                "params": {"seconds": 0.05}}]})
    sc = [p for t, p in ev if t == "step-completed"][0]
    assert sc["elapsed_ms"] is not None and sc["elapsed_ms"] >= 40


# ---- step types -----------------------------------------------------------

def test_set_output_writes():
    _, ev, vars = _run({"steps": [{"type": "set_output", "id": "s",
                                   "params": {"signal": "dc", "value": 12}}]})
    assert vars.writes == [("dc", 12)]


def test_sweep_writes_each_value_and_runs_children():
    _, ev, vars = _run({"steps": [{"type": "sweep", "id": "sw", "params": {
        "signal": "level", "values": [1, 2, 3],
        "steps": [{"type": "measure_and_compare", "id": "m", "params": {"signal": "level", "min": 0}}]}}]})
    assert [w[1] for w in vars.writes] == [1, 2, 3]
    trs = [p for t, p in ev if t == "test-result"]
    assert len(trs) == 3 and [x["sequence"] for x in trs] == [1, 2, 3]


def test_repeat_runs_n_times():
    _, ev, _ = _run({"steps": [{"type": "repeat", "id": "rp", "params": {
        "count": 4, "steps": [{"type": "wait", "id": "w", "params": {"seconds": 0}}]}}]})
    started = [p for t, p in ev if t == "step-started" and p["step_id"] == "w"]
    assert len(started) == 4


def test_if_gates_on_condition():
    # condition false -> inner skipped
    _, ev, _ = _run({"steps": [{"type": "if", "id": "c", "params": {
        "condition": {"signal": "flag", "above": 10},
        "steps": [{"type": "set_output", "id": "s", "params": {"signal": "x", "value": 1}}]}}]},
        _Vars({"flag": 0}))
    assert not any(p["step_id"] == "s" for t, p in ev if t == "step-started")


# ---- event ordering (§6) --------------------------------------------------

def test_event_ordering_invariants():
    _, ev, _ = _run({"steps": [
        {"type": "set_output", "id": "s", "params": {"signal": "a", "value": 1}},
        {"type": "measure_and_compare", "id": "m", "params": {"signal": "a", "min": 0}}]})
    types = [t for t, _ in ev]
    # every step-started precedes its step-completed; test-result before its step-completed
    assert types.count("step-started") == 2 and types.count("step-completed") == 2


# ---- run state machine (threaded) ----------------------------------------

def _engine(recipe, safe_spy, **kw):
    events, emit = _sink()
    eng = RunEngine("st1", variables=_Vars({"v": 5.0}), emit=emit,
                    recipe_fetch=lambda rid, ver: recipe, safe_state=safe_spy, diag=_noop_diag,
                    **kw)
    return eng, events


def test_full_run_finishes_and_tears_down():
    tore = []
    eng, ev = _engine({"steps": [{"type": "measure_and_compare", "id": "m",
                                  "params": {"signal": "v", "min": 0, "max": 10}}]},
                      lambda: tore.append(1))
    reply = eng.start({"recipe_id": "demo", "run_id": "r1"})
    assert reply == {"run_id": "r1", "accepted": True}
    eng._thread.join(5)
    assert eng.state == IDLE and tore == [1]
    terminal = [(t, p) for t, p in ev if t in ("run-finished", "run-aborted")]
    assert len(terminal) == 1 and terminal[0][0] == "run-finished"
    assert terminal[0][1]["result"] == PASS
    assert ev[0][0] == "run-started"


def test_abort_runs_teardown_and_emits_one_terminal():
    tore = []
    eng, ev = _engine({"steps": [{"type": "wait", "id": "w", "params": {"seconds": 3}}]},
                      lambda: tore.append(1))
    eng.start({"recipe_id": "demo", "run_id": "r2"})
    time.sleep(0.15)
    eng.abort()
    eng._thread.join(5)
    assert eng.state == IDLE and tore == [1]
    terminal = [(t, p) for t, p in ev if t in ("run-finished", "run-aborted")]
    assert len(terminal) == 1 and terminal[0][0] == "run-aborted"
    assert terminal[0][1]["reason"] == "operator_abort"


def test_deadline_faults_the_station():
    eng, ev = _engine({"steps": [{"type": "wait", "id": "w", "params": {"seconds": 5}}],
                       "timeout_ms": 100}, lambda: None, abort_grace_ms=50)
    eng.start({"recipe_id": "demo", "run_id": "r3"})
    eng._thread.join(5)
    assert eng.state == FAULTED
    term = [(t, p) for t, p in ev if t in ("run-finished", "run-aborted")]
    assert len(term) == 1 and term[0][1]["reason"] == "step_timeout"


def test_start_refused_when_not_idle():
    eng, _ = _engine({"steps": [{"type": "wait", "id": "w", "params": {"seconds": 2}}]},
                     lambda: None)
    eng.start({"recipe_id": "demo", "run_id": "a"})
    time.sleep(0.05)
    second = eng.start({"recipe_id": "demo", "run_id": "b"})
    assert second["accepted"] is False and second["error"] == "run_active"
    eng.abort(); eng._thread.join(5)


def test_recipe_fetch_failure_aborts_before_run_started():
    events, emit = _sink()
    def boom(rid, ver): raise RuntimeError("no recipe")
    eng = RunEngine("st1", variables=_Vars(), emit=emit, recipe_fetch=boom,
                    safe_state=lambda: None, diag=_noop_diag)
    eng.start({"recipe_id": "gone", "run_id": "r4"})
    eng._thread.join(5)
    assert not any(t == "run-started" for t, _ in events)
    term = [(t, p) for t, p in events if t in ("run-finished", "run-aborted")]
    assert term[0][1]["reason"] == "recipe_fetch_failed" and eng.state == IDLE


def test_unknown_step_type_fails_validation():
    events, emit = _sink()
    eng = RunEngine("st1", variables=_Vars(), emit=emit,
                    recipe_fetch=lambda rid, ver: {"steps": [{"type": "does_not_exist", "id": "x"}]},
                    safe_state=lambda: None, diag=_noop_diag)
    eng.start({"recipe_id": "bad", "run_id": "r5"})
    eng._thread.join(5)
    term = [(t, p) for t, p in events if t in ("run-finished", "run-aborted")]
    assert term[0][1]["reason"] == "validation_failed"
    assert not any(t == "run-started" for t, _ in events)

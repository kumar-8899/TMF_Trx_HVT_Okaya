"""D14 + D5 — graded reads retry a transient failure, report only the last attempt, and a read
that still raises becomes one FAIL row with value ERROR (never a silent or absent failure).
StepAborted is never retried or turned into a failed reading."""

import time

import pytest

import controller.step_types  # noqa: F401 — registers the 8 core types
from controller.context import StepAborted
from controller.results import FAIL, PASS
from controller.sequencer import Sequencer


class _FlakyVars:
    """read() raises `raises` times, then returns `value`."""

    def __init__(self, value=5.0, raises=0, exc=None):
        self.value = value
        self.raises = raises
        self.exc = exc or OSError("connection reset")
        self.reads = 0

    def read(self, name):
        self.reads += 1
        if self.reads <= self.raises:
            raise self.exc
        return {"value": self.value}

    def write(self, name, value):
        return {"written": value}


def _run(recipe, vars, aborted=False):
    events = []
    seq = Sequencer(vars, lambda t, p: events.append((t, p)), lambda *a, **k: None)
    result = seq.run(recipe, run_id="r1", station="st1", run_parameters={},
                     deadline_ts=time.monotonic() + 10, aborted_fn=lambda: aborted)
    return result, events


def _step(**params):
    base = {"signal": "v", "settle_s": 0}       # 0 s pause keeps the test fast
    base.update(params)
    return {"steps": [{"type": "measure_and_compare", "id": "m", "params": base}]}


def test_transient_read_exception_recovers():
    v = _FlakyVars(value=5.0, raises=1)
    r, ev = _run(_step(min=0, max=10, retries=2), v)
    assert r == PASS and v.reads == 2           # first raised, second succeeded
    trs = [p for t, p in ev if t == "test-result"]
    assert len(trs) == 1 and trs[0]["result"] == PASS   # only the last attempt is reported


def test_graded_fail_is_reread_and_last_attempt_wins():
    v = _FlakyVars(value=99.0, raises=0)        # out of limits on every read
    r, ev = _run(_step(min=0, max=10, retries=2), v)
    assert r == FAIL and v.reads == 3           # 1 + 2 retries
    trs = [p for t, p in ev if t == "test-result"]
    assert len(trs) == 1 and trs[0]["result"] == FAIL and trs[0]["measured"] == 99.0


def test_persistent_exception_is_one_fail_row_error():
    v = _FlakyVars(raises=99)
    r, ev = _run(_step(min=0, max=10, retries=2), v)
    assert r == FAIL and v.reads == 3
    trs = [p for t, p in ev if t == "test-result"]
    assert len(trs) == 1 and trs[0]["result"] == FAIL and trs[0]["measured"] == "ERROR"


def test_good_read_unchanged_without_retries():
    v = _FlakyVars(value=5.0, raises=0)
    r, ev = _run(_step(min=0, max=10), v)       # retries defaults to 0
    assert r == PASS and v.reads == 1


def test_step_aborted_is_never_retried():
    class _AbortVars:
        def __init__(self):
            self.reads = 0

        def read(self, name):
            self.reads += 1
            raise StepAborted()

        def write(self, name, value):
            return {"written": value}

    v = _AbortVars()
    with pytest.raises(StepAborted):
        _run(_step(min=0, max=10, retries=3), v)
    assert v.reads == 1                          # aborted on the first read; never retried

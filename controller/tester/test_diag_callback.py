"""The REAL diagnostics callable (`controller.__main__.diag_publisher`) against the real Sequencer.

Regression: v1.31.0's D5 made the sequencer log `step.end` with a `message=<step message>` field, but the controller's
callable was `lambda level, message, **f`, so every step end raised
`TypeError: ... got multiple values for argument 'message'` and the run aborted right after its FIRST step
(seen live: a hipot test measured PASS, then `run-aborted reason=error`). The framework's own tests missed it because
their fake diag names the parameter `msg`. These tests use the production callable.
"""

import time

import controller.step_types  # noqa: F401 — registers the 8 core types
from controller.__main__ import diag_publisher
from controller.results import FAIL, PASS
from controller.sequencer import Sequencer


class _Client:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, **kw):
        self.published.append((topic, payload))


class _Vars:
    def __init__(self, values=None):
        self.signals = dict(values or {})

    def read(self, name):
        return {"value": self.signals.get(name, 0.0)}

    def write(self, name, value):
        self.signals[name] = value
        return {"written": value}


def _run(recipe, values=None):
    client, events = _Client(), []
    seq = Sequencer(_Vars(values), lambda t, p: events.append((t, p)), diag_publisher(client))
    verdict = seq.run(recipe, run_id="r1", station="st1", run_parameters={},
                      deadline_ts=time.monotonic() + 10, aborted_fn=lambda: False)
    return verdict, events, [p for _t, p in client.published]


_PASS = {"type": "measure_and_compare", "id": "ok", "params": {"signal": "v", "max": 100}}
_FAIL = {"type": "measure_and_compare", "id": "bad", "params": {"signal": "v", "min": 100}}


def test_a_passing_step_end_no_longer_aborts_the_run():
    verdict, events, diags = _run({"steps": [_PASS, _PASS | {"id": "ok2"}]}, {"v": 5})
    assert verdict == PASS
    assert [p["step_id"] for t, p in events if t == "step-started"] == ["ok", "ok2"]     # BOTH steps ran
    assert [d["context"]["step_id"] for d in diags if d["message"] == "step.end"] == ["ok", "ok2"]


def test_a_failed_step_logs_its_cause_in_the_context_not_the_message_parameter():
    verdict, _, diags = _run({"steps": [_FAIL]}, {"v": 5})
    assert verdict == FAIL
    (end,) = [d for d in diags if d["message"] == "step.end"]
    assert end["level"] == "warning" and end["message"] == "step.end"                 # the message IS the event name
    assert "message" in end["context"]                                                # the step's own message rides in context


def test_any_diag_caller_may_pass_a_field_called_message_or_level():
    client = _Client()
    diag = diag_publisher(client)
    diag("error", "teardown failed", message="boom", level="x", station="st1")
    (_topic, p), = client.published
    assert (p["level"], p["message"]) == ("error", "teardown failed")
    assert p["context"] == {"message": "boom", "level": "x", "station": "st1"}
    assert _topic == "diag"

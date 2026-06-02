"""Diagnostics bus (CORE.md §1, LABVIEW_BRIDGE §4 shape)."""

import pytest

from core.services.diagnostics import Diagnostics


def _bus():
    events = []
    diag = Diagnostics("st1", "0.0.0", sinks=[events.append])
    return diag, events


def test_emit_shape_and_seq():
    diag, events = _bus()
    diag.info("daq", "hello", resource="Dev1")
    diag.warning("daq", "watch out")
    assert [e["seq"] for e in events] == [1, 2]
    e = events[0]
    assert e["level"] == "info"
    assert e["subsystem"] == "daq"
    assert e["message"] == "hello"
    assert e["context"] == {"resource": "Dev1"}
    assert e["exception"] is None
    assert e["station"] == "st1" and e["source_version"] == "0.0.0"
    assert events[1]["level"] == "warning"


def test_exception_captures_traceback():
    diag, events = _bus()
    try:
        raise ValueError("boom")
    except ValueError as exc:
        diag.exception("core", "caught", exc)
    e = events[0]
    assert e["level"] == "error"
    assert e["exception"]["type"] == "ValueError"
    assert "boom" in e["exception"]["message"]
    assert "Traceback" in e["exception"]["traceback"]


def test_timed_success_emits_elapsed():
    diag, events = _bus()
    with diag.timed("core", "did work"):
        pass
    assert events[0]["level"] == "info"
    assert "elapsed_ms" in events[0]["context"]


def test_timed_failure_emits_error_and_reraises():
    diag, events = _bus()
    with pytest.raises(RuntimeError):
        with diag.timed("core", "work"):
            raise RuntimeError("nope")
    assert events[0]["level"] == "error"
    assert events[0]["exception"]["type"] == "RuntimeError"
    assert "elapsed_ms" in events[0]["context"]


def test_broken_sink_does_not_kill_emitter():
    def bad(_):
        raise IOError("disk full")

    good = []
    diag = Diagnostics("st1", "0.0.0", sinks=[bad, good.append])
    diag.info("core", "still works")
    assert len(good) == 1

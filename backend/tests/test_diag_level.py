"""Diagnostics per-subsystem level control + `critical` (REMOTE_DEBUG.md §3.5)."""

from core.services.diagnostics import LEVELS, Diagnostics


def _diag(**kw):
    out: list[dict] = []
    return Diagnostics("st1", "1.0", sinks=[out.append], **kw), out


def test_default_floor_emits_everything():
    d, out = _diag()
    d.debug("daq", "a")
    d.info("daq", "b")
    assert len(out) == 2   # unchanged behavior: default floor is debug


def test_set_level_gates_emission_at_source():
    d, out = _diag()
    d.set_level("daq", "warning")
    filtered = d.info("daq", "hidden")        # below floor → not emitted, returns {}
    d.warning("daq", "shown")
    d.info("runs", "other")                   # a different subsystem is unaffected
    msgs = [e["message"] for e in out]
    assert filtered == {} and "hidden" not in msgs
    assert "shown" in msgs and "other" in msgs


def test_critical_is_a_level():
    d, out = _diag()
    assert "critical" in LEVELS
    d.critical("safety", "trip")
    assert out[-1]["level"] == "critical"


def test_get_levels_shape():
    d, _ = _diag()
    d.set_level("daq", "error")
    assert d.get_levels() == {"default": "debug", "overrides": {"daq": "error"}}


def test_default_level_floor_can_be_raised():
    d, out = _diag(default_level="info")
    d.debug("daq", "hidden")
    d.info("daq", "shown")
    assert [e["message"] for e in out] == ["shown"]


def test_unknown_level_rejected():
    d, _ = _diag()
    try:
        d.set_level("daq", "verbose")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

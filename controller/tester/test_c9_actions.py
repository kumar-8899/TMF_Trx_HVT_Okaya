"""C9 — non-scalar actions: ctx.invoke resolves an action name against the calling station's
map and calls the capability method; capability↔instance bindings are verified at config load
(PYTHON_CONTROLLER.md §9.4, §4.1)."""

import pytest

from controller.context import StepContext
from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import (StationVariables, VariableError,
                                             check_action_capabilities)
from controller.loop import AsyncLoopThread
from tester import _fakelib


def _registry():
    lib = _fakelib.ensure_registered()
    mux = _fakelib.ensure_mux_registered()
    loop = AsyncLoopThread(); loop.start()
    reg = InstrumentRegistry(loop)
    reg.build([
        {"id": "psu1", "library": lib, "simulated": True, "params": {"resource": "p"}, "stations": ["st1"]},
        {"id": "mux1", "library": mux, "simulated": True, "params": {"resource": "m"}, "stations": ["st1"]},
    ])
    loop.run(reg.connect_all())
    return reg, loop


_MAP = {"signals": {}, "actions": {"signal_mux": {"instance": "mux1", "capability": "multiplexer"}}}


# ---- capability verification at load (§4.1) -------------------------------

def test_capability_check_passes_for_correct_binding():
    reg, loop = _registry()
    try:
        assert check_action_capabilities({"st1": _MAP}, reg) == []
    finally:
        loop.stop()


def test_capability_check_refuses_wrong_capability():
    reg, loop = _registry()
    try:
        bad = {"st1": {"actions": {"scope": {"instance": "psu1", "capability": "dso"}}}}
        errs = check_action_capabilities(bad, reg)
        assert errs and "does not implement" in errs[0] and "dso" in errs[0]
    finally:
        loop.stop()


def test_capability_check_refuses_unknown_instance():
    reg, loop = _registry()
    try:
        bad = {"st1": {"actions": {"m": {"instance": "ghost", "capability": "multiplexer"}}}}
        errs = check_action_capabilities(bad, reg)
        assert errs and "unknown/unloaded instance" in errs[0]
    finally:
        loop.stop()


# ---- ctx.invoke (§9.4) ----------------------------------------------------

def _ctx(variables):
    return StepContext(station="st1", run_id="r", trace="t", run_parameters={},
                       variables=variables, deadline_ts=9e18, aborted_fn=lambda: False,
                       diag_fn=lambda *a, **k: None, child_runner=lambda s, c: None)


def test_invoke_positional_args_reach_the_instance():
    reg, loop = _registry()
    try:
        v = StationVariables("st1", _MAP, reg, loop)
        ctx = _ctx(v)
        ctx.invoke("signal_mux", "set_route", [3, "busA"])
        assert reg.get("mux1").routes == {3: "busA"}          # the args landed on the device
        assert ctx.invoke("signal_mux", "get_routes") == {3: "busA"}
    finally:
        loop.stop()


def test_invoke_keyword_args():
    reg, loop = _registry()
    try:
        v = StationVariables("st1", _MAP, reg, loop)
        _ctx(v).invoke("signal_mux", "set_route", {"channel": 7, "bus": "busB"})
        assert reg.get("mux1").routes == {7: "busB"}
    finally:
        loop.stop()


def test_invoke_unknown_action_raises():
    reg, loop = _registry()
    try:
        v = StationVariables("st1", _MAP, reg, loop)
        with pytest.raises(VariableError, match="unknown action"):
            _ctx(v).invoke("nope", "set_route", [1, "b"])
    finally:
        loop.stop()


def test_invoke_on_faulted_instance_fails_fast():
    reg, loop = _registry()
    try:
        reg.mark_faulted(["mux1"])                             # a safety trip disabled it (§10.3)
        v = StationVariables("st1", _MAP, reg, loop)
        with pytest.raises(VariableError, match="faulted"):
            _ctx(v).invoke("signal_mux", "set_route", [1, "b"])
    finally:
        loop.stop()

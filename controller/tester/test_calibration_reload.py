"""D3 / X2 — `calibration.reload`: swap a station's scales in place, no relaunch
(docs/contracts/CALIBRATION.md). Only `scale` may change; a rewired binding, a changed signal set,
a busy station or a bad file are refused and leave the live scales untouched."""

import json

import pytest

from controller.instruments.variables import StationVariables, VariableError
from controller.loop import AsyncLoopThread
from controller.serve import register_calibration_ops


@pytest.fixture(scope="module")
def loop():
    lt = AsyncLoopThread()
    lt.start()
    yield lt
    lt.stop()


class _Inst:
    async def invoke(self, method, *args):
        return 3.0


class _Reg:
    def require(self, _id):
        return _Inst()


def _sig(gain=2.0, offset=1.0, **kw):
    return {"instance": "daq", "read": "read_ai", "scale": {"gain": gain, "offset": offset}, **kw}


def _vars(loop, signals):
    return StationVariables("st1", {"signals": signals, "actions": {}}, _Reg(), loop)


def test_reload_changes_scale_in_place(loop):
    v = _vars(loop, {"a": _sig()})
    held = v.signals                                     # a holder of the dict sees the swap
    assert v.read("a")["value"] == 7.0
    assert v.reload({"signals": {"a": _sig(10.0, 0.0, calibrated=True)}}) == {"reloaded": 1}
    assert v.read("a")["value"] == 30.0 and held is v.signals


@pytest.mark.parametrize("change", [{"instance": "other"}, {"read": "read_x"}, {"args": [1]},
                                    {"clamp": {"max": 1}}])
def test_reload_refuses_a_rewired_binding(loop, change):
    v = _vars(loop, {"a": _sig()})
    with pytest.raises(VariableError, match="restart"):
        v.reload({"signals": {"a": _sig(9.0, 0.0, **change)}})
    assert v.read("a")["value"] == 7.0                   # live scale untouched


def test_reload_refuses_a_changed_signal_set(loop):
    v = _vars(loop, {"a": _sig()})
    with pytest.raises(VariableError, match="signal set"):
        v.reload({"signals": {"a": _sig(), "b": _sig()}})
    with pytest.raises(VariableError, match="signal set"):
        v.reload({"signals": {}})


class _Client:
    station = "st1"

    def __init__(self):
        self.ops = {}

    def serve(self, op, handler, **_):
        self.ops[op] = handler


class _Engine:
    def __init__(self, state="idle"):
        self.state = state


def _op(loop, tmp_path, state="idle", content=None):
    v = _vars(loop, {"a": _sig()})
    p = tmp_path / "eff.json"
    p.write_text(content or json.dumps({"signals": {"a": _sig(10.0, 0.0)}}), encoding="utf-8")
    c = _Client()
    register_calibration_ops(c, v, _Engine(state), p)
    return c.ops["calibration.reload"], v


def test_op_reloads_when_idle(loop, tmp_path):
    op, v = _op(loop, tmp_path)
    assert op({}) == {"ok": True, "result": {"reloaded": 1}}
    assert v.read("a")["value"] == 30.0


def test_op_refused_mid_run(loop, tmp_path):
    op, v = _op(loop, tmp_path, state="running")
    r = op({})
    assert r["ok"] is False and r["error"]["code"] == "Busy"
    assert v.read("a")["value"] == 7.0


def test_op_bad_file_is_a_structured_error_and_keeps_scales(loop, tmp_path):
    op, v = _op(loop, tmp_path, content="{nope")
    r = op({})
    assert r["ok"] is False and r["error"]["message"]
    assert v.read("a")["value"] == 7.0

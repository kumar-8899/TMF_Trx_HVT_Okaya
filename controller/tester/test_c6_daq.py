"""C6 — DAQ AI/DI streaming + reads (PYTHON_CONTROLLER.md §9.5). Sim source, no card."""

import time

from controller.daq import DaqController, register_daq_ops


def _daq(collector, **cfg):
    base = {"rate_hz": 200, "batch": 5, "simulated": True}
    base.update(cfg)
    return DaqController("st1", lambda sub, p, qos: collector.append((sub, p, qos)), config=base)


def test_ai_stream_publishes_batched_qos0_frames():
    frames = []
    daq = _daq(frames, ai_channels=["ai0", "ai1"])
    r = daq.stream_start("ai", {})
    assert r["started"] and r["channels"] == ["ai0", "ai1"] and daq.is_running("ai")
    time.sleep(0.12)
    daq.stream_stop("ai")
    assert not daq.is_running("ai")
    assert len(frames) >= 2
    sub, p, qos = frames[0]
    assert sub == "stream/ai" and qos == 0                 # streams are QoS 0 (§9.5)
    assert set(p["channels"]) == {"ai0", "ai1"}
    assert len(p["channels"]["ai0"]) == 5                  # `batch` samples per frame


def test_stop_halts_publishing():
    frames = []
    daq = _daq(frames)
    daq.stream_start("ai", {"channels": 1})
    time.sleep(0.08)
    daq.stream_stop("ai")
    time.sleep(0.02)
    n = len(frames)
    time.sleep(0.1)
    assert len(frames) == n                                # nothing after stop


def test_di_stream_is_boolean():
    frames = []
    daq = _daq(frames)
    daq.stream_start("di", {"channels": 2})
    time.sleep(0.06)
    daq.stream_stop("di")
    p = frames[0][1]
    assert set(p["channels"]) == {"di0", "di1"}
    assert all(isinstance(v, bool) for v in p["channels"]["di0"])


def test_read_one_sample():
    daq = _daq([])
    r = daq.read("ai", {"channels": ["ai0", "ai1"]})
    assert set(r["result"]["channels"]) == {"ai0", "ai1"}


def test_register_daq_ops_serves_the_op_set():
    served = {}
    class _C:
        def serve(self, op, h): served[op] = h
        def publish(self, *a, **k): pass
    daq = _daq([])
    register_daq_ops(_C(), daq)
    assert {"daq.ai.stream.start", "daq.ai.stream.stop", "daq.ai.read",
            "daq.di.stream.start", "daq.di.stream.stop", "daq.di.read"} <= set(served)
    assert served["daq.ai.stream.start"]({})["started"] is True
    daq.stop_all()

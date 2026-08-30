"""SnapshotBuffer (REMOTE_DEBUG.md §3.4) — four triggers, warnings never trigger,
compact arrays, 5 s tail, hourly cap."""

import json

from debug_server.capture import parse
from debug_server.config import SnapshotConfig
from debug_server.snapshot import SnapshotBuffer

ST = "st1"


def _buf(tmp_path, **kw):
    cfg = SnapshotConfig(**{"pre_seconds": 30, "post_seconds": 5, "max_per_hour": 6, **kw})
    b = SnapshotBuffer(cfg, tmp_path)
    b._sync = True
    return b


def _val(name, value, ts):
    return parse(f"tmf/{ST}/value/{name}", ST, json.dumps({"name": name, "value": value, "ts": ts}))


def _diag(level, ts, sub="controller", msg="x"):
    return parse(f"tmf/{ST}/diag/{sub}", ST,
                 json.dumps({"ts": ts, "level": level, "subsystem": sub, "message": msg, "context": {}}))


def test_error_triggers_one_compact_snapshot_with_tail(tmp_path):
    b = _buf(tmp_path)
    for i in range(10):
        b.observe(_val("vbus", 12.0 - i * 0.1, 100.0 + i * 0.1))   # ts 100.0 .. 100.9
    b.observe(_diag("error", 101.0))                               # arm: deadline 106.0
    b.observe(_val("vbus", 9.0, 103.0))                            # within tail, buffered
    b.observe(_val("vbus", 8.5, 106.5))                            # ts >= deadline → flush

    files = list(tmp_path.glob("snapshot-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    meta = json.loads(lines[0])["__snapshot__"]
    assert meta["trigger"].startswith("error:")
    var = json.loads(lines[1])
    assert var["var"] == "vbus" and "t0" in var and isinstance(var["v"], list)  # compact arrays
    assert 9.0 in var["v"]                                         # the 5 s tail is included


def test_warning_never_triggers(tmp_path):
    b = _buf(tmp_path)
    b.observe(_val("vbus", 12.0, 100.0))
    b.observe(_diag("warning", 101.0))
    b.observe(_val("vbus", 12.0, 107.0))
    assert list(tmp_path.glob("snapshot-*.jsonl")) == []


def test_step_failure_event_triggers(tmp_path):
    b = _buf(tmp_path)
    b.observe(_val("vbus", 12.0, 100.0))
    fail = parse(f"tmf/{ST}/event/test-result", ST, json.dumps(
        {"type": "test-result", "ts": 101.0, "payload": {"run_id": "R1", "test_name": "ACW", "result": "FAIL"}}))
    b.observe(fail)
    b.observe(_val("vbus", 11.0, 107.0))   # past the tail → flush
    files = list(tmp_path.glob("snapshot-*.jsonl"))
    assert len(files) == 1
    meta = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])["__snapshot__"]
    assert meta["trigger"].startswith("step_failure:") and meta["run_id"] == "R1"


def test_hourly_cap_suppresses_and_counts(tmp_path):
    b = _buf(tmp_path, max_per_hour=2)
    t = 100.0
    for _ in range(4):
        b.observe(_val("v", 1.0, t))
        b.observe(_diag("error", t + 0.1))
        b.observe(_val("v", 1.0, t + 6.0))   # flush past the 5 s tail
        t += 10.0
    assert len(list(tmp_path.glob("snapshot-*.jsonl"))) == 2
    assert b.suppressed == 2

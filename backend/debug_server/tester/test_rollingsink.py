"""RollingSink (REMOTE_DEBUG.md §3.3/§5) — drop-and-count, rotation, deferred gzip,
eviction, read-back. Drives the writer synchronously (no thread) for determinism."""

from debug_server.config import RollingConfig
from debug_server.rollingsink import RollingSink


def _sink(tmp_path, *, queue_size=20_000, file_cap=200, total_cap=10_000, compress=True):
    cfg = RollingConfig(enabled=True, dir=str(tmp_path), max_file_mb=1, max_total_mb=1,
                        compress_rotated=compress, retention_days=None)
    s = RollingSink(cfg, tmp_path, queue_size=queue_size)
    s._file_cap = file_cap
    s._total_cap = total_cap
    return s


def _rec(i, run="R1"):
    return {"seq": i, "ts": 100.0 + i, "kind": "value", "subtopic": "value/v",
            "payload": {"name": "v", "value": i, "run_id": run}}


def test_enqueue_drops_and_counts_never_blocks(tmp_path):
    s = _sink(tmp_path, queue_size=3)
    for i in range(6):
        s.enqueue(_rec(i))     # never blocks even though the queue holds 3
    assert s.dropped == 3
    assert s._q.qsize() == 3


def test_rotation_and_gzip_when_idle(tmp_path):
    s = _sink(tmp_path, file_cap=120)
    for i in range(6):
        s.enqueue(_rec(i))
        s._drain_once(block=False)
    # rotated files were gzipped immediately (no active run)
    assert list(tmp_path.glob("debug-*.jsonl.gz"))
    assert not list(tmp_path.glob("debug-*.jsonl"))    # none left uncompressed


def test_gzip_deferred_during_active_run(tmp_path):
    s = _sink(tmp_path, file_cap=120)
    s.set_active_run(True)
    for i in range(6):
        s.enqueue(_rec(i))
        s._drain_once(block=False)
    # during a run, rotated files stay uncompressed (compression deferred)
    assert list(tmp_path.glob("debug-*.jsonl"))
    assert not list(tmp_path.glob("debug-*.jsonl.gz"))
    s.set_active_run(False)                            # run ends → now compress
    assert list(tmp_path.glob("debug-*.jsonl.gz"))
    assert not list(tmp_path.glob("debug-*.jsonl"))


def test_eviction_keeps_total_under_cap(tmp_path):
    s = _sink(tmp_path, file_cap=100, total_cap=300, compress=False)
    for i in range(40):
        s.enqueue(_rec(i))
        s._drain_once(block=False)
    total = sum(f.stat().st_size for f in tmp_path.glob("debug*"))
    assert total <= 300


def test_read_filters_by_run(tmp_path):
    s = _sink(tmp_path, file_cap=10_000, compress=False)
    for i in range(3):
        s.enqueue(_rec(i, run="R1"))
    for i in range(3, 5):
        s.enqueue(_rec(i, run="R2"))
    s._drain_once(block=False)
    r1 = list(s.read(run_id="R1"))
    assert {x["seq"] for x in r1} == {0, 1, 2}
    windowed = list(s.read(since=103.0))
    assert all(x["ts"] >= 103.0 for x in windowed)


def test_metrics_shape(tmp_path):
    s = _sink(tmp_path)
    s.enqueue(_rec(1))
    s._drain_once(block=False)
    m = s.metrics()
    assert {"rolling_dropped", "bytes_written_today", "bytes_per_run_avg",
            "projected_mb_per_day", "disk_free_mb", "days_retained_at_current_rate"} <= set(m)
    assert m["bytes_written_today"] > 0

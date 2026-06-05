"""logs standalone tester (CORE.md §6.2). L1 registration; L2 sink + dedup."""

import modules.logs  # noqa: F401 — import registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from modules.logs.sink import LogsDiagSink
from modules.logs.variants.db import DbLogs


class Rows:
    """A repo.put-shaped collector for sink tests."""

    def __init__(self):
        self.rows = []

    async def put(self, record_type, data, *, summary=None, id=None):
        self.rows.append({"type": record_type, "data": data, "summary": summary})
        return f"id{len(self.rows)}"


def _err(message="boom", level="warning", subsystem="daq", ts=1000.0):
    return {"ts": ts, "level": level, "subsystem": subsystem, "message": message,
            "context": {}, "exception": None, "seq": 1}


def test_registered():
    rec = default_registry.get("logs")
    assert rec.variant_ids == ["db"]
    assert default_registry.variant("logs", "db") is DbLogs


def test_manifest_valid():
    m = ManifestLoader().load("logs")
    assert m.entitlement_key == "logs"
    assert m.variants == ["db"]
    assert m.contributes.api_prefix == "/logs"
    assert set(m.core_dependencies) == {"db", "bridge", "config", "auth", "diag", "web"}


async def test_skeleton_lifecycle():
    core = CoreServices(station="st1")
    mod = DbLogs.construct(core, {})
    await mod.init()
    await mod.start()
    health = await mod.health()
    assert health.status.value == "ok"
    await mod.stop()


# --- L2: sink + dedup ------------------------------------------------------


async def test_burst_coalesces_to_two_rows():
    r = Rows()
    sink = LogsDiagSink(r.put, min_level="warning", window_s=10.0)
    for i in range(47):
        await sink.handle(_err(ts=1000.0 + i * 0.1))
    assert len(r.rows) == 1  # only the first occurrence written so far
    await sink.flush_expired(now=1100.0)  # window closed
    assert len(r.rows) == 2
    assert r.rows[0]["data"]["repeat_count"] == 1 and r.rows[0]["data"]["coalesced"] is False
    coalesced = r.rows[1]["data"]
    assert coalesced["repeat_count"] == 47 and coalesced["coalesced"] is True
    assert coalesced["window_start"] == 1000.0


async def test_distinct_messages_not_coalesced():
    r = Rows()
    sink = LogsDiagSink(r.put, window_s=10.0)
    await sink.handle(_err(message="A"))
    await sink.handle(_err(message="B"))
    await sink.flush_all()
    assert len(r.rows) == 2  # two firsts, no coalesced rows


async def test_min_level_filters():
    r = Rows()
    sink = LogsDiagSink(r.put, min_level="warning")
    await sink.handle(_err(level="info"))
    await sink.handle(_err(level="debug"))
    assert r.rows == []
    await sink.handle(_err(level="error"))
    assert len(r.rows) == 1


async def test_subsystems_allowlist():
    r = Rows()
    sink = LogsDiagSink(r.put, subsystems=("daq",))
    await sink.handle(_err(subsystem="ui"))
    assert r.rows == []
    await sink.handle(_err(subsystem="daq"))
    assert len(r.rows) == 1


async def test_summary_and_source_default():
    r = Rows()
    sink = LogsDiagSink(r.put)
    await sink.handle(_err(message="TDMS write failed", level="error"))
    assert r.rows[0]["summary"] == "[error] daq: TDMS write failed"
    assert r.rows[0]["data"]["source"] == "python"


async def test_dedup_disabled_writes_every_event():
    r = Rows()
    sink = LogsDiagSink(r.put, dedup_enabled=False)
    for _ in range(5):
        await sink.handle(_err())
    assert len(r.rows) == 5

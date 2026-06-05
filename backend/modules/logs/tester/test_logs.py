"""logs standalone tester (CORE.md §6.2). L1 registration; L2 sink + dedup."""

import asyncio

import pytest

import modules.logs  # noqa: F401 — import registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.auth_verify import Principal
from core.services.db import Database
from core.services.diagnostics import Diagnostics
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
    core = CoreServices(diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
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


# --- L3: db variant — diag wiring, record_action, queries ------------------


@pytest.fixture
async def ctx():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(
        db=db, diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
    )
    mod = DbLogs.construct(core, {})
    await mod.init()
    yield mod, core, db
    await db.close()


async def _drain(mod):
    sink = mod._sink
    while not sink._queue.empty():
        await sink.handle(sink._queue.get_nowait())
    await sink.flush_all()


async def test_diag_bus_wired_persists_error(ctx):
    mod, core, db = ctx
    core.diag.error("daq", "kaboom", code=-2501)  # in-process diag -> sink
    await _drain(mod)
    rows = await db.repo.query("error_log")
    assert len(rows) == 1
    assert rows[0]["data"]["message"] == "kaboom"
    assert rows[0]["data"]["source"] == "python"
    assert rows[0]["summary"] == "[error] daq: kaboom"


async def test_record_action_attribution(ctx):
    mod, _, db = ctx
    p = Principal("op1", role="operator")
    await mod.record_action(p, "recipe.save", "board/v4", "success", {"version": 4})
    rows = await db.repo.query("action_log")
    d = rows[0]["data"]
    assert d["user"] == "op1" and d["role"] == "operator" and d["action"] == "recipe.save"
    assert rows[0]["summary"] == "op1 recipe.save board/v4 -> success"


async def test_query_actions_filters(ctx):
    mod, _, _ = ctx
    p = Principal("op1", role="operator")
    q = Principal("eng", role="engineer")
    await mod.record_action(p, "recipe.save", "r1", "success")
    await mod.record_action(p, "recipe.delete", "r2", "failure")
    await mod.record_action(q, "run.start", "x", "success")

    assert {r["data"]["user"] for r in (await mod.query_actions(user="op1"))["items"]} == {"op1"}
    recipes = await mod.query_actions(action="recipe.")
    assert all(r["data"]["action"].startswith("recipe.") for r in recipes["items"])
    assert len(recipes["items"]) == 2
    fails = await mod.query_actions(result="failure")
    assert len(fails["items"]) == 1


async def test_query_errors_level_minimum(ctx):
    mod, _, db = ctx
    for lvl in ("warning", "error", "critical", "info"):
        await db.repo.put("error_log", {"level": lvl, "subsystem": "daq", "message": lvl,
                                        "source": "python"}, summary=lvl)
    assert len((await mod.query_errors())["items"]) == 4
    high = await mod.query_errors(level="error")
    assert {r["data"]["level"] for r in high["items"]} == {"error", "critical"}


async def test_cursor_pagination_stable_under_appends(ctx):
    mod, _, _ = ctx
    p = Principal("op1", role="operator")
    ids = []
    for i in range(3):
        ids.append(await mod.record_action(p, f"a.{i}", "t", "success"))
        await asyncio.sleep(0.01)  # strictly increasing ts

    page1 = await mod.query_actions(limit=2)
    assert len(page1["items"]) == 2 and page1["next_cursor"]

    await asyncio.sleep(0.01)
    ids.append(await mod.record_action(p, "a.3", "t", "success"))  # arrives mid-paging

    page2 = await mod.query_actions(limit=10, cursor=page1["next_cursor"])
    got = [r["id"] for r in page1["items"]] + [r["id"] for r in page2["items"]]
    assert len(got) == len(set(got))   # no duplicates
    assert set(got) == set(ids)        # page1 stable; new row shows in page2

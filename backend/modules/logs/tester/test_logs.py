"""logs standalone tester (CORE.md §6.2). L1 registration; L2 sink + dedup."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

import modules.logs  # noqa: F401 — import registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.auth_verify import AuthError, Principal, TokenVerifier
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
        db=db, auth=TokenVerifier(),
        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1",
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


# --- L4: REST + permissions ------------------------------------------------


_TOKENS = {
    "viewer": Principal("v", role="viewer", permissions=frozenset({"DIAGNOSTICS.VIEW"})),
    "admin": Principal("a", role="admin", permissions=frozenset({"DIAGNOSTICS.*"})),
    "noperm": Principal("n", role="operator", permissions=frozenset({"TEST.RUN"})),
}


def _client(mod, core):
    core.auth.register(lambda t: _TOKENS[t] if t in _TOKENS else _raise())
    app = FastAPI()
    app.state.auth = core.auth
    app.include_router(mod.router, prefix="/logs")
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _raise():
    raise AuthError("bad token")


async def _seed(mod, db):
    await mod.record_action(Principal("op1", role="operator"), "recipe.save", "r1", "success")
    await db.repo.put("error_log", {"level": "error", "subsystem": "daq", "message": "e",
                                    "source": "python"}, summary="[error] daq: e")


async def test_rest_read_gated_view(ctx):
    mod, core, db = ctx
    await _seed(mod, db)
    async with _client(mod, core) as c:
        v = {"Authorization": "Bearer viewer"}
        assert (await c.get("/logs/errors")).status_code == 401           # no token
        assert (await c.get("/logs/errors", headers=v)).status_code == 200
        assert (await c.get("/logs/actions", headers=v)).status_code == 200
        stats = await c.get("/logs/stats", headers=v)
        assert stats.status_code == 200
        assert stats.json()["error_counts"]["error"] == 1
        assert stats.json()["action_counts"]["total"] == 1
        # lacks DIAGNOSTICS.VIEW
        assert (await c.get("/logs/errors", headers={"Authorization": "Bearer noperm"})).status_code == 403


async def test_rest_delete_gated_purge(ctx):
    mod, core, db = ctx
    await _seed(mod, db)
    async with _client(mod, core) as c:
        viewer = {"Authorization": "Bearer viewer"}
        admin = {"Authorization": "Bearer admin"}
        # viewer has VIEW but not PURGE
        assert (await c.delete("/logs/errors?before=9999999999", headers=viewer)).status_code == 403
        d = await c.delete("/logs/errors?before=9999999999", headers=admin)
        assert d.status_code == 200 and d.json()["deleted"] == 1
        assert (await c.get("/logs/errors", headers=viewer)).json()["items"] == []


# --- L5: run-event subscriber + pruning ------------------------------------


async def test_run_event_becomes_action(ctx):
    mod, _, _ = ctx
    await mod._on_event("tmf/st1/event/run-started", {"type": "run-started", "ts": 1.0,
                                                      "payload": {"run_id": "R1"}})
    await mod._on_event("tmf/st1/event/step-completed", {"type": "step-completed", "ts": 1.1,
                                                         "payload": {"run_id": "R1"}})
    acts = (await mod.query_actions())["items"]
    assert len(acts) == 1  # only run-* mapped; step-* ignored
    assert acts[0]["data"]["action"] == "run.start"
    assert acts[0]["data"]["user"] == "controller"
    assert acts[0]["data"]["target"] == "R1"


async def test_run_events_carry_result_reason_and_system_aborts_fail(ctx):
    mod, core, _ = ctx
    ev = lambda t, **b: mod._on_event(f"tmf/st1/event/{t}", {"type": t, "ts": 1.0, "payload": b})  # noqa: E731
    await ev("run-finished", run_id="R1", result="PASS", recipe_id="rcp")
    await ev("run-aborted", run_id="R2", reason="operator_abort")
    await ev("run-aborted", run_id="R3", reason="validation_failed", errors=["bad step"])
    await ev("run-aborted", run_id="R4", reason="safety:overtemp")
    by = {a["data"]["target"]: a["data"] for a in (await mod.query_actions())["items"]}
    assert (by["R1"]["result"], by["R1"]["detail"]["result"], by["R1"]["detail"]["recipe_id"]) == ("success", "PASS", "rcp")
    assert by["R2"]["result"] == "success"                       # operator abort is not a fault
    assert by["R3"]["result"] == "failure" and by["R3"]["detail"]["reason"] == "validation_failed"
    assert by["R3"]["detail"]["errors"] == ["bad step"]
    assert by["R4"]["result"] == "failure"


def test_prune_decision_pure():
    from modules.logs.variants.db import _prune_decision
    rows = [{"ts": float(i)} for i in range(10)]  # ts 0..9
    # keep newest 2, only delete beyond max_days; max_days huge -> nothing old
    assert _prune_decision(rows, max_days=3650, max_records=2, now=100.0) is None
    # max_days 0 -> all older; floor keeps 2 -> delete 8 (ts < rows[8].ts == 8.0)
    assert _prune_decision(rows, max_days=0, max_records=2, now=100.0) == 8.0
    # floor >= count -> nothing
    assert _prune_decision(rows, max_days=0, max_records=20, now=100.0) is None


async def test_prune_once_honors_caps(ctx):
    _, core, db = ctx
    mod = DbLogs.construct(core, {"retention": {"error_log": {"max_days": 0, "max_records": 2}}})
    for i in range(5):
        await db.repo.put("error_log", {"level": "error", "subsystem": "daq",
                                        "message": f"e{i}", "source": "python"}, summary="e")
        await asyncio.sleep(0.01)
    deleted = await mod.prune_once()
    assert deleted["error_log"] == 3
    assert len(await db.repo.query("error_log")) == 2  # newest kept

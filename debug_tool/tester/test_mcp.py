"""The Debug Tool over real HTTP: token gate, sharing session, per-action human approval, MCP tool set, downloads."""

import asyncio
import contextlib
import json
import socket

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from debug_tool.app import build_app, create_runtime
from debug_tool.engine import EngineConfig
from debug_tool.mcp_server import ACTION_TOOLS, PASSIVE_TOOLS, cap
from debug_tool.tester.test_engine import FEED, core_transport, fake_subscriber, make_app


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Rig:
    def __init__(self, base, rt, port):
        self.base, self.rt, self.port = base, rt, port
        self.url = f"{base}/mcp"
        self.op = {"X-Operator-Key": rt.operator_key}

    async def share(self, hours=1.0):
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{self.base}/operator/sharing/start", json={"hours": hours}, headers=self.op)
            r.raise_for_status()
            self.token = r.json()["token"]
            return r.json()

    @contextlib.asynccontextmanager
    async def session(self, token=None, extra_headers=None):
        headers = {"Authorization": f"Bearer {token or self.token}", **(extra_headers or {})}
        async with streamablehttp_client(self.url, headers=headers, terminate_on_close=False) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                yield s

    async def pending(self, n=1, timeout=5.0):
        async with httpx.AsyncClient() as c:
            end = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < end:
                p = (await c.get(f"{self.base}/operator/approvals", headers=self.op)).json()["pending"]
                if len(p) >= n:
                    return p
                await asyncio.sleep(0.05)
        raise AssertionError("no approval card appeared")

    async def decide(self, rid, approve, **extra):
        async with httpx.AsyncClient() as c:
            return await c.post(f"{self.base}/operator/approvals/{rid}", json={"approve": approve, **extra}, headers=self.op)


@contextlib.asynccontextmanager
async def running(tmp_path, *, timeout_s=30.0, records=FEED, http_factory=None, heartbeat_s=0.2):
    app_info = make_app(tmp_path)
    cfg = EngineConfig(app=app_info, data_dir=tmp_path / "tool", in_app_probe=lambda p: False)
    rt = create_runtime(cfg, approval_timeout_s=timeout_s, subscriber=fake_subscriber(records), http_factory=http_factory)
    port = free_port()
    app = build_app(rt, bind_host="127.0.0.1", port=port, heartbeat_s=heartbeat_s)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    await asyncio.sleep(0.1)
    try:
        yield Rig(f"http://127.0.0.1:{port}", rt, port)
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


def data(result):
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


# ------------------------------------------------------------------------------------------------ the gate

@pytest.mark.asyncio
async def test_nothing_is_reachable_until_the_operator_turns_sharing_on(tmp_path):
    async with running(tmp_path) as rig:
        async with httpx.AsyncClient() as c:
            assert (await c.get(f"{rig.base}/healthz")).status_code == 200            # liveness only, no data
            for path in ("/mcp", "/debug/health", "/files/x"):
                r = await c.get(f"{rig.base}{path}", headers={"Authorization": "Bearer anything"})
                assert r.status_code == 403 and r.headers["content-type"].startswith("application/problem+json")
        await rig.share()
        async with httpx.AsyncClient() as c:
            assert (await c.get(f"{rig.base}/debug/health", headers={"Authorization": "Bearer wrong"})).status_code == 401
            assert (await c.get(f"{rig.base}/debug/health")).status_code == 401
            ok = await c.get(f"{rig.base}/debug/health", headers={"Authorization": f"Bearer {rig.token}"})
            assert ok.status_code == 200 and ok.json()["tool"] == "tmf-debug-tool"


@pytest.mark.asyncio
async def test_stop_ends_access_immediately(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        async with httpx.AsyncClient() as c:
            assert (await c.post(f"{rig.base}/operator/sharing/stop", headers=rig.op)).json()["stopped"] is True
            assert (await c.get(f"{rig.base}/debug/health", headers={"Authorization": f"Bearer {rig.token}"})).status_code == 403


@pytest.mark.asyncio
async def test_the_mcp_token_can_never_approve_its_own_request(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        async with httpx.AsyncClient() as c:
            bearer = {"Authorization": f"Bearer {rig.token}"}
            assert (await c.get(f"{rig.base}/operator/approvals", headers=bearer)).status_code == 401
            assert (await c.post(f"{rig.base}/operator/approvals/abc", json={"approve": True}, headers=bearer)).status_code == 401
            assert (await c.post(f"{rig.base}/operator/approvals/abc", json={"approve": True},
                                 headers={"X-Operator-Key": "guess"})).status_code == 401
            assert (await c.get(f"{rig.base}/operator/status", headers=rig.op)).status_code == 200


def test_binding_to_all_interfaces_is_refused(tmp_path):
    rt = create_runtime(EngineConfig(app=make_app(tmp_path), data_dir=tmp_path / "t"))
    for host in ("0.0.0.0", "::", ""):
        with pytest.raises(ValueError, match="specific address"):
            build_app(rt, bind_host=host)


# ------------------------------------------------------------------------------------------------ the tool set

@pytest.mark.asyncio
async def test_tools_list_and_annotations_separate_passive_from_action(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        async with rig.session() as s:
            tools = {t.name: t for t in (await s.list_tools()).tools}
            assert set(PASSIVE_TOOLS) | set(ACTION_TOOLS) <= set(tools)
            for n in PASSIVE_TOOLS:
                assert tools[n].annotations.readOnlyHint is True and tools[n].annotations.openWorldHint is False, n
            for n in ACTION_TOOLS:
                assert tools[n].annotations.readOnlyHint is False and tools[n].annotations.openWorldHint is True, n
            assert tools["bench_level_set"].annotations.destructiveHint is True
            assert [r.uri.unicode_string() for r in (await s.list_resources()).resources] == ["tmf://bench/health"]
            assert "diagnose-run" in [p.name for p in (await s.list_prompts()).prompts]


@pytest.mark.asyncio
async def test_a_wrong_token_cannot_open_an_mcp_session(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        with pytest.raises(BaseException):
            async with rig.session(token="nope"):
                pass


@pytest.mark.asyncio
async def test_passive_tools_work_with_no_approval_and_label_bench_text_untrusted(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        await asyncio.sleep(0.1)
        async with rig.session() as s:
            h = data(await s.call_tool("bench_health", {}))
            assert h["ok"] and h["data"]["live"]["mqtt"] == "connected" and "untrusted_content" not in h
            ev = data(await s.call_tool("bench_events", {"subsystem": "instrument", "level": "error"}))
            assert ev["ok"] and [e["message"] for e in ev["data"]["events"]] == ["psu1.measure error: boom"]
            assert "DATA" in ev["untrusted_content"]
            why = data(await s.call_tool("bench_why", {}))
            assert why["data"]["run"] == "R1"
            inst = data(await s.call_tool("bench_instruments", {}))
            assert inst["data"]["instruments"]["psu1"]["failed_calls"] == 1
            logs = data(await s.call_tool("bench_logs", {"source": "nope"}))
            assert "unknown log source" in logs["data"]["note"]
            fol = data(await s.call_tool("bench_follow", {"seconds": 0.6, "sources": "mqtt"}))
            assert fol["ok"] and fol["data"]["window_s"] == 0.6
            bad = data(await s.call_tool("bench_snapshot", {"snapshot_id": "zzz"}))
            assert bad["ok"] is False and bad["error"]["type"] == "NotFound"
            assert (await rig_pending(rig)) == []                                  # nothing was ever queued


async def rig_pending(rig):
    async with httpx.AsyncClient() as c:
        return (await c.get(f"{rig.base}/operator/approvals", headers=rig.op)).json()["pending"]


# ------------------------------------------------------------------------------------------------ the human in the loop

@pytest.mark.asyncio
async def test_an_action_blocks_until_a_human_approves_and_shows_what_will_run(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        async with rig.session() as s:
            call = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "repro"}))
            card = (await rig.pending())[0]
            assert card["kind"] == "capture" and "repro" in card["summary"] and card["details"] == {"name": "repro"}
            await asyncio.sleep(0.4)
            assert not call.done()                                                 # still waiting for the person
            assert (await rig.decide(card["id"], True)).json()["decision"] == "approved"
            out = data(await asyncio.wait_for(call, 5))
            assert out["ok"] and out["decision"] == "approved" and out["data"]["name"] == "repro" and out["approved_by"]
        log = rig.rt.log.tail(100)
        assert any(e.get("event") == "approval_decided" and e.get("approved") and e.get("by") for e in log)
        assert any(e.get("event") == "tool_call" and e.get("tool") == "bench_capture_start" for e in log)


@pytest.mark.asyncio
async def test_deny_and_timeout_come_back_as_structured_results_and_nothing_runs(tmp_path):
    async with running(tmp_path, timeout_s=0.6) as rig:
        await rig.share()
        async with rig.session() as s:
            call = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "a"}))
            await rig.decide((await rig.pending())[0]["id"], False)
            denied = data(await call)
            assert denied["ok"] is False and denied["decision"] == "denied" and "denied" in denied["message"]
            timed = data(await s.call_tool("bench_capture_start", {"name": "b"}))        # nobody answers
            assert timed["ok"] is False and timed["decision"] == "timeout"
        assert rig.rt.engine.ingestor._captures == {}                                    # neither request executed


@pytest.mark.asyncio
async def test_approving_one_request_never_authorises_another(tmp_path):
    async with running(tmp_path, timeout_s=1.5) as rig:
        await rig.share()
        async with rig.session() as s:
            a = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "A"}))
            b = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "B"}))
            cards = await rig.pending(2)
            first = next(c for c in cards if c["details"]["name"] == "A")
            await rig.decide(first["id"], True)
            ra, rb = data(await a), data(await b)
            assert ra["ok"] and ra["data"]["name"] == "A"
            assert rb["ok"] is False and rb["decision"] == "timeout"                    # B needed its own click
        assert len(rig.rt.engine.ingestor._captures) == 1


@pytest.mark.asyncio
async def test_stopping_sharing_cancels_pending_requests_and_blocks_new_ones(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        async with rig.session() as s:
            await s.list_tools()                                                   # prime the client's schema cache (it re-lists after a call)
            call = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "x"}))
            await rig.pending()
            async with httpx.AsyncClient() as c:
                assert (await c.post(f"{rig.base}/operator/sharing/stop", headers=rig.op)).json()["denied_pending"] == 1
            out = data(await asyncio.wait_for(call, 5))
            assert out["ok"] is False and out["decision"] == "stopped"
        with pytest.raises(BaseException):
            async with rig.session():
                pass


@pytest.mark.asyncio
async def test_progress_notifications_say_we_are_waiting_for_the_operator(tmp_path):
    async with running(tmp_path, heartbeat_s=0.15) as rig:
        await rig.share()
        seen = []

        async def on_progress(progress, total, message):
            seen.append(message)
        async with rig.session() as s:
            call = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "p"}, progress_callback=on_progress))
            card = (await rig.pending())[0]
            await asyncio.sleep(0.6)
            await rig.decide(card["id"], True)
            await asyncio.wait_for(call, 5)
        assert seen and all("operator" in m for m in seen)


@pytest.mark.asyncio
async def test_the_tool_itself_refuses_when_sharing_is_off_and_never_queues(tmp_path):
    from debug_tool.mcp_server import build_mcp
    rt = create_runtime(EngineConfig(app=make_app(tmp_path), data_dir=tmp_path / "t"))
    _mcp, host = build_mcp(rt.engine, rt.sharing, rt.approvals, rt.log)
    ran = []

    async def run(d):
        ran.append(1)
        return {}
    out = await host.action(None, "t", "capture", "x", {}, run)
    assert out["ok"] is False and out["error"]["type"] == "SharingOff" and not ran and rt.approvals.pending() == []


@pytest.mark.asyncio
async def test_an_approved_request_does_not_run_if_sharing_ended_while_the_card_was_open(tmp_path):
    from debug_tool.mcp_server import build_mcp
    rt = create_runtime(EngineConfig(app=make_app(tmp_path), data_dir=tmp_path / "t"))
    _mcp, host = build_mcp(rt.engine, rt.sharing, rt.approvals, rt.log)
    rt.sharing.start(1.0)
    ran = []

    async def run(d):
        ran.append(1)
        return {}
    task = asyncio.create_task(host.action(None, "t", "capture", "x", {}, run))
    await asyncio.sleep(0.05)
    rid = rt.approvals.pending()[0]["id"]
    rt.sharing.stop("operator")                       # Stop pressed...
    rt.approvals.decide(rid, True, by="op")           # ...and the already-open card is clicked anyway
    out = await task
    assert out["ok"] is False and out["decision"] == "stopped" and not ran


# ------------------------------------------------------------------------------------------------ actions that reach the core / disk

@pytest.mark.asyncio
async def test_level_set_needs_the_core_token_then_waits_for_approval_then_applies(tmp_path):
    state = {"calls": []}
    async with running(tmp_path, http_factory=lambda: httpx.AsyncClient(transport=core_transport(state))) as rig:
        await rig.share()
        async with rig.session() as s:
            no_token = data(await s.call_tool("bench_level_set", {"subsystem": "daq", "level": "debug"}))
            assert no_token["ok"] is False and no_token["error"]["type"] == "PermissionError"
            assert (await rig_pending(rig)) == []                                       # the operator was not bothered
        async with rig.session(extra_headers={"X-Core-Token": "coretok"}) as s:
            bad = data(await s.call_tool("bench_level_set", {"subsystem": "daq", "level": "loud"}))
            assert bad["error"]["type"] == "ValueError"
            call = asyncio.create_task(s.call_tool("bench_level_set", {"subsystem": "daq", "level": "debug", "ttl_minutes": 5}))
            card = (await rig.pending())[0]
            assert card["kind"] == "level_set" and "'daq' to debug for 5 min" in card["summary"]
            await rig.decide(card["id"], True)
            out = data(await asyncio.wait_for(call, 5))
            assert out["ok"] and out["data"]["applied"] == {"daq": "debug"} and out["data"]["will_revert_to"] == "warning"
            lv = data(await s.call_tool("bench_level_get", {}))
            assert lv["data"]["overrides"] == {"daq": "debug"}
    # `running` stopped the engine, which cancelled the pending revert task cleanly


@pytest.mark.asyncio
async def test_export_is_an_action_and_the_zip_is_downloadable_only_with_the_token(tmp_path, monkeypatch):
    from debug_server import sysinfo
    monkeypatch.setattr(sysinfo, "processes", lambda: {"processes": []})
    monkeypatch.setattr(sysinfo, "app_health", lambda port=None: {"app_running": False, "note": "n"})
    async with running(tmp_path) as rig:
        await rig.share()
        async with rig.session() as s:
            call = asyncio.create_task(s.call_tool("bench_export", {"rows": 200, "integrity": False}))
            card = (await rig.pending())[0]
            assert card["kind"] == "export" and "diagnostics bundle" in card["summary"] and "recorder files" in card["details"]["includes"]
            await rig.decide(card["id"], True)
            out = data(await asyncio.wait_for(call, 30))
            assert out["ok"] and out["data"]["download_url"].startswith("/files/")
        async with httpx.AsyncClient() as c:
            url = rig.base + out["data"]["download_url"]
            assert (await c.get(url)).status_code == 401
            got = await c.get(url, headers={"Authorization": f"Bearer {rig.token}"})
            assert got.status_code == 200 and got.content[:2] == b"PK"
            assert (await c.get(f"{rig.base}/files/unknown", headers={"Authorization": f"Bearer {rig.token}"})).status_code == 404


# ------------------------------------------------------------------------------------------------ result capping

def test_cap_halves_the_biggest_list_and_says_so():
    big = {"ok": True, "data": {"events": [{"m": "x" * 200} for _ in range(2000)], "small": [1, 2, 3]}}
    out = cap(big, limit=20_000)
    assert len(json.dumps(out)) <= 20_000 and out["data"]["small"] == [1, 2, 3]
    assert out["truncated"]["lists"]["events"]["of"] == 2000 and out["truncated"]["lists"]["events"]["kept"] < 2000


def test_cap_leaves_small_results_alone_and_shortens_giant_strings():
    small = {"ok": True, "data": {"a": 1}}
    assert cap(small) is small
    out = cap({"ok": True, "data": {"raw": "y" * 100_000}}, limit=20_000)
    assert len(json.dumps(out)) <= 20_000 and "chars)" in out["data"]["raw"]

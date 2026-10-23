"""Scripts, file reads and instrument probes over MCP: each waits for a human, shows the exact request, and is refused up front
(before any card) when policy says it could never run."""

import asyncio
import json
import sys

import pytest

from debug_tool.tester.test_mcp import data, rig_pending, running
from debug_tool.tester.test_probe import FakeCore


def sys_python(rig):
    rig.rt.engine.scripts._python = lambda: {"kind": "system", "path": sys.executable, "version": "x", "notes": []}


@pytest.mark.asyncio
async def test_a_script_runs_only_after_the_operator_reads_and_approves_its_exact_text(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        sys_python(rig)
        script = "print('psu check', 6 * 7)"
        async with rig.session() as s:
            call = asyncio.create_task(s.call_tool("bench_run_script", {"interpreter": "python", "script": script, "timeout_s": 30}))
            card = (await rig.pending())[0]
            assert card["kind"] == "run_script" and card["details"]["script"] == script and len(card["details"]["sha256"]) == 64
            assert "sha256 " + card["details"]["sha256"][:12] in card["summary"] and card["details"]["timeout_s"] == 30
            assert not (tmp_path / "tool" / "scripts").exists()                          # nothing runs while the card is open
            await rig.decide(card["id"], True)
            out = data(await asyncio.wait_for(call, 30))
            assert out["ok"] and out["data"]["exit_code"] == 0 and "psu check 42" in out["data"]["stdout"]
            assert out["decision"] == "approved" and out["approved_by"] and "untrusted_content" in out
        saved = list((tmp_path / "tool" / "scripts").glob("*.py"))
        assert len(saved) == 1 and saved[0].name.endswith(card["details"]["sha256"][:12] + ".py")


@pytest.mark.asyncio
async def test_a_denied_script_never_runs_and_a_bad_request_never_reaches_the_operator(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        sys_python(rig)
        async with rig.session() as s:
            call = asyncio.create_task(s.call_tool("bench_run_script", {"interpreter": "python", "script": "open('x.txt','w')"}))
            await rig.decide((await rig.pending())[0]["id"], False)
            assert data(await call)["decision"] == "denied"
            assert not (tmp_path / "tool" / "scripts").exists()
            bad = data(await s.call_tool("bench_run_script", {"interpreter": "bash", "script": "ls"}))
            assert bad["ok"] is False and bad["error"]["type"] == "ScriptError"
            empty = data(await s.call_tool("bench_run_script", {"interpreter": "python", "script": "  "}))
            assert empty["ok"] is False
            assert (await rig_pending(rig)) == []


@pytest.mark.asyncio
async def test_scripts_during_a_test_need_the_approver_to_tick_the_box(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        sys_python(rig)
        rig.rt.engine.ingestor._active = True                                          # a test run is in progress
        async with rig.session() as s:
            call = asyncio.create_task(s.call_tool("bench_run_script", {"interpreter": "python", "script": "print('x')"}))
            card = (await rig.pending())[0]
            assert card["details"]["run_active_now"] is True and "TEST RUN IS IN PROGRESS" in card["details"]["warning"]
            await rig.decide(card["id"], True)                                          # approved, but the box was not ticked
            refused = data(await call)
            assert refused["ok"] is False and refused["error"]["type"] == "RunActive" and refused["decision"] == "approved"
            assert not (tmp_path / "tool" / "scripts").exists()
            call = asyncio.create_task(s.call_tool("bench_run_script", {"interpreter": "python", "script": "print('x')"}))
            await rig.decide((await rig.pending())[0]["id"], True, allow_during_run=True)
            assert data(await asyncio.wait_for(call, 30))["data"]["stdout"].strip() == "x"


@pytest.mark.asyncio
async def test_read_file_is_confined_redacted_and_approved(tmp_path):
    async with running(tmp_path) as rig:
        await rig.share()
        root = rig.rt.engine.app.state_root
        (root / "config" / "app.json").write_text('{"report_db": {"password": "hunter2"}, "stations": ["st1"]}', encoding="utf-8")
        outside = tmp_path / "secret.txt"
        outside.write_text("private")
        async with rig.session() as s:
            out = data(await s.call_tool("bench_read_file", {"path": str(outside)}))
            assert out["ok"] is False and out["error"]["type"] == "FileRefused" and (await rig_pending(rig)) == []
            call = asyncio.create_task(s.call_tool("bench_read_file", {"path": "config/app.json"}))
            card = (await rig.pending())[0]
            assert card["kind"] == "read_file" and card["details"]["path"].endswith("app.json")
            await rig.decide(card["id"], True)
            res = data(await asyncio.wait_for(call, 10))
            assert res["ok"] and "hunter2" not in res["data"]["text"] and '"stations"' in res["data"]["text"]
            assert res["data"]["redacted_values"] == 1


@pytest.mark.asyncio
async def test_instrument_probe_refuses_writes_up_front_and_relays_reads_after_approval(tmp_path):
    core = FakeCore([12.5])
    async with running(tmp_path, http_factory=core.client) as rig:
        await rig.share()
        async with rig.session() as s:                                                   # no core token
            out = data(await s.call_tool("bench_instrument_probe", {"instance_id": "psu1", "method": "identify"}))
            assert out["ok"] is False and out["error"]["type"] == "PermissionError"
        async with rig.session(extra_headers={"X-Core-Token": "tok"}) as s:
            for method in ("set_voltage", "output_enable", "safe_state"):
                refused = data(await s.call_tool("bench_instrument_probe", {"instance_id": "psu1", "method": method, "args": [5]}))
                assert refused["ok"] is False and refused["error"]["type"] == "ProbeRefused", method
            assert (await rig_pending(rig)) == [] and core.calls == []                   # the operator was never asked; nothing was sent
            call = asyncio.create_task(s.call_tool("bench_instrument_probe", {"instance_id": "psu1", "method": "measure_voltage"}))
            card = (await rig.pending())[0]
            assert card["kind"] == "instrument_probe" and card["details"]["kind"] == "read-only" and "psu1" in card["summary"]
            await rig.decide(card["id"], True)
            res = data(await asyncio.wait_for(call, 15))
            assert res["ok"] and res["data"]["result"] == 12.5 and len(core.calls) == 1
            rig.rt.engine.ingestor._active = True
            during = data(await s.call_tool("bench_instrument_probe", {"instance_id": "psu1", "method": "measure_voltage"}))
            assert during["ok"] is False and "test run is in progress" in during["error"]["message"]
            assert (await rig_pending(rig)) == []
            rig.rt.engine.ingestor._active = False
            call = asyncio.create_task(s.call_tool("bench_instrument_poll", {"instance_id": "psu1", "method": "measure_voltage",
                                                                             "samples": 3, "interval_s": 0.5}))
            card = (await rig.pending())[0]
            assert card["kind"] == "instrument_poll" and card["details"]["samples"] == 3
            await rig.decide(card["id"], True)
            poll = data(await asyncio.wait_for(call, 30))
            assert poll["ok"] and poll["data"]["ok_samples"] == 3 and poll["data"]["stats"]["mean"] == 12.5
        log = json.dumps(rig.rt.log.tail(200))
        assert "instrument_probe" in log and "approval_decided" in log

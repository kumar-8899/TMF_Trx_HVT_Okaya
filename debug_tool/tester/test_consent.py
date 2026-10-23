"""debug_tool.consent - sharing session, approval queue, access log. Pure logic, injectable clock."""

import asyncio
import json

import pytest

from debug_tool.consent import (ACTION_KINDS, AccessLog, ApprovalQueue, ConsentError, SharingState)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# ---- sharing ------------------------------------------------------------------------------------

def test_sharing_is_off_by_default_and_a_wrong_or_missing_token_never_passes():
    s = SharingState(clock=Clock())
    assert not s.active() and not s.check_token("anything") and not s.check_token(None) and s.fingerprint() is None


def test_start_issues_a_token_that_works_until_expiry_then_everything_is_refused():
    clk = Clock()
    s = SharingState(clock=clk)
    tok = s.start(hours=1)
    assert s.active() and s.check_token(tok) and not s.check_token(tok + "x") and not s.check_token("")
    clk.t += 3599
    assert s.check_token(tok)
    clk.t += 2                                              # past the hour
    assert not s.active() and not s.check_token(tok) and s.status()["on"] is False


def test_stop_ends_sharing_immediately_and_a_restart_gets_a_new_token():
    s = SharingState(clock=Clock())
    t1 = s.start(1)
    s.stop()
    assert not s.check_token(t1)
    t2 = s.start(1)
    assert t2 != t1 and s.check_token(t2) and not s.check_token(t1)


@pytest.mark.parametrize("hours", [0, -1, 25, 1000])
def test_sharing_duration_is_bounded(hours):
    with pytest.raises(ConsentError):
        SharingState(clock=Clock()).start(hours)


def test_status_never_exposes_the_token_only_a_fingerprint():
    s = SharingState(clock=Clock())
    tok = s.start(2)
    st = s.status()
    assert tok not in json.dumps(st) and st["fingerprint"] and len(st["fingerprint"]) == 8 and st["seconds_left"] == 7200
    s.touch("10.0.0.7")
    assert s.status()["session"]["remote"] == "10.0.0.7" and s.status()["session"]["requests"] == 1


# ---- approvals ----------------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def test_an_action_waits_for_a_human_and_approval_unblocks_it():
    async def go():
        q = ApprovalQueue(timeout_s=5)
        task = asyncio.create_task(q.request("run_script", "run diag.ps1", {"script": "Get-Process"}))
        await asyncio.sleep(0.05)
        assert not task.done()                                       # blocked: nobody approved yet
        [p] = q.pending()
        assert p["kind"] == "run_script" and p["details"]["script"] == "Get-Process"
        assert q.decide(p["id"], True, by="engineer", extra={"allow_during_run": True})
        d = await task
        assert d.approved and d.reason == "approved" and d.by == "engineer" and d.extra == {"allow_during_run": True}
        assert q.pending() == []
    run(go())


def test_deny_and_timeout_and_stop_are_denials_with_distinct_reasons():
    async def go():
        q = ApprovalQueue(timeout_s=5)
        t = asyncio.create_task(q.request("read_file", "read x"))
        await asyncio.sleep(0.02)
        q.decide(q.pending()[0]["id"], False, by="eng")
        assert (await t).reason == "denied"

        d = await ApprovalQueue(timeout_s=0.05).request("level_set", "debug on")
        assert not d.approved and d.reason == "timeout"

        t2 = asyncio.create_task(q.request("export", "bundle"))
        await asyncio.sleep(0.02)
        assert q.deny_all("stopped") == 1
        assert (await t2).reason == "stopped"
    run(go())


def test_one_approval_authorises_exactly_one_request():
    async def go():
        q = ApprovalQueue(timeout_s=5)
        a = asyncio.create_task(q.request("run_script", "A"))
        b = asyncio.create_task(q.request("run_script", "B"))
        await asyncio.sleep(0.05)
        pa, pb = sorted(q.pending(), key=lambda p: p["summary"])
        q.decide(pa["id"], True, by="eng")
        assert (await a).approved
        await asyncio.sleep(0.05)
        assert not b.done()                                          # approving A did not approve B
        assert [p["summary"] for p in q.pending()] == ["B"]
        assert q.decide(pa["id"], True) is False                     # an already-decided id cannot be approved again
        q.decide(pb["id"], False)
        assert not (await b).approved
    run(go())


def test_deciding_an_unknown_id_is_false_and_history_records_outcomes():
    async def go():
        q = ApprovalQueue(timeout_s=0.05)
        assert q.decide("nope", True) is False
        await q.request("capture", "start capture")
        h = q.history()
        assert h[-1]["kind"] == "capture" and h[-1]["decision"] == "timeout"
    run(go())


def test_progress_callback_tells_the_caller_it_is_waiting():
    async def go():
        msgs = []
        q = ApprovalQueue(timeout_s=0.05)
        await q.request("probe", "identify psu1", on_progress=msgs.append)
        assert msgs and "waiting for the operator" in msgs[0] and "identify psu1" in msgs[0]
    run(go())


def test_the_action_class_covers_everything_that_touches_the_pc():
    assert {"run_script", "read_file", "instrument_probe", "instrument_poll", "level_set", "capture", "export"} == set(ACTION_KINDS)


# ---- access log ---------------------------------------------------------------------------------

def test_access_log_records_and_tails(tmp_path):
    log = AccessLog(tmp_path / "access.jsonl", clock=Clock())
    for i in range(5):
        log.write(event="request", path=f"/p{i}")
    assert [r["path"] for r in log.tail(3)] == ["/p2", "/p3", "/p4"] and log.tail(1)[0]["ts"] == 1000.0


def test_access_log_is_size_capped_and_keeps_one_backup(tmp_path):
    log = AccessLog(tmp_path / "a.jsonl", max_bytes=400)
    for i in range(40):
        log.write(event="request", path=f"/path/{i}", pad="x" * 20)
    assert (tmp_path / "a.jsonl").stat().st_size <= 400 + 200
    assert (tmp_path / "a.jsonl.1").is_file()
    assert log.tail(100)[-1]["path"] == "/path/39"                  # newest survives; the file never grows unbounded


def test_decisions_and_sharing_events_land_in_the_log(tmp_path):
    log = AccessLog(tmp_path / "a.jsonl")
    s = SharingState(clock=Clock(), log=log)
    s.start(1)
    s.stop()

    async def go():
        q = ApprovalQueue(timeout_s=0.05, log=log)
        await q.request("run_script", "script X", {"sha256": "abc"})
    run(go())
    events = [r["event"] for r in log.tail(20)]
    assert events == ["sharing_started", "sharing_stopped", "approval_requested", "approval_decided"]
    assert "token" not in json.dumps(log.tail(20))

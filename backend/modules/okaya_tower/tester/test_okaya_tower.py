"""okaya_tower: the relay2 tower stack driven from run lifecycle. Unit-level — a fake bridge
records the variable.write calls, so no broker/controller/relay is needed."""

from __future__ import annotations

import asyncio

from core.framework.contract import CoreServices
from modules.okaya_tower.variants.default import OkayaTower


class FakeBridge:
    def __init__(self):
        self.writes: list[tuple[str, int, str]] = []     # (signal, value, station)

    async def request(self, op, args, station=None, timeout=None):
        if op == "variable.write":
            self.writes.append((args["name"], args["value"], station))
            return {"result": {"name": args["name"], "written": args["value"]}}
        return {}


class FakeRepo:
    def __init__(self):
        self.store: dict = {}

    async def get(self, t, i):
        return self.store.get((t, i))

    async def put(self, t, data, id=None, summary=None):
        self.store[(t, id)] = {"data": dict(data)}
        return {"id": id}


class FakeDb:
    def __init__(self):
        self.repo = FakeRepo()


class FakeDiag:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...


async def _mk(db=None, **cfg):
    bridge = FakeBridge()
    core = CoreServices(db=db or FakeDb(), bridge=bridge, diag=FakeDiag(), station="st1")
    m = OkayaTower.construct(core, {"buzzer_duration_s": 0.02, "result_hold_s": 0.02, **cfg})
    await m.init()
    return m, bridge


def _evt(etype, **body):
    return (f"tmf/st1/event/{etype}", {"type": etype, "payload": body})


def _run(coro):
    return asyncio.run(coro)


def _lit(writes, signal, value):
    return (signal, value, "st1") in writes


def test_pass_lights_green_only_then_clears_to_off():
    async def go():
        m, b = await _mk()
        await m._on_event(*_evt("run-finished", run_id="R1", result="PASS"))
        assert _lit(b.writes, "tl_green", 1) and _lit(b.writes, "tl_red", 0)
        assert not _lit(b.writes, "buzzer", 1)              # buzzer never sounds on a pass
        await m._seq                                        # let the hold expire
        assert b.writes[-1] == ("tl_green", 0, "st1")       # cleared to idle (off)
    _run(go())


def test_fail_lights_red_and_buzzes_then_clears():
    async def go():
        m, b = await _mk()
        await m._on_event(*_evt("run-finished", run_id="R1", result="FAIL"))
        assert _lit(b.writes, "tl_red", 1) and _lit(b.writes, "tl_green", 0)
        assert _lit(b.writes, "buzzer", 1)
        await m._seq
        assert _lit(b.writes, "buzzer", 0)                  # buzzer stopped after its duration
        assert b.writes[-1] == ("tl_red", 0, "st1")         # red cleared after the hold
    _run(go())


def test_fail_does_not_buzz_when_buzzer_disabled():
    async def go():
        m, b = await _mk(buzzer_enabled=False)
        await m._on_event(*_evt("run-finished", run_id="R1", result="FAIL"))
        assert _lit(b.writes, "tl_red", 1)
        assert not any(sig == "buzzer" and val == 1 for sig, val, _ in b.writes)
        await m._seq
    _run(go())


def test_abort_is_red_without_the_buzzer():
    async def go():
        m, b = await _mk()
        await m._on_event(*_evt("run-aborted", run_id="R1", reason="operator"))
        assert _lit(b.writes, "tl_red", 1)
        assert not any(sig == "buzzer" and val == 1 for sig, val, _ in b.writes)
        await m._seq
    _run(go())


def test_run_started_turns_everything_off_while_testing():
    async def go():
        m, b = await _mk()
        await m._on_event(*_evt("run-started", run_id="R1"))
        assert _lit(b.writes, "tl_green", 0) and _lit(b.writes, "tl_red", 0) and _lit(b.writes, "buzzer", 0)
        assert not any(val == 1 for _, val, _ in b.writes)   # nothing is ever lit while testing
    _run(go())


def test_a_new_run_start_cancels_a_pending_result_hold():
    async def go():
        m, b = await _mk(result_hold_s=100)                 # long hold we would otherwise wait on
        await m._on_event(*_evt("run-finished", result="PASS"))
        assert _lit(b.writes, "tl_green", 1)
        await m._on_event(*_evt("run-started", run_id="R2"))  # next part starts
        assert m._seq is None                                # the hold timer was cancelled
        assert b.writes[-3:] == [("tl_green", 0, "st1"), ("tl_red", 0, "st1"), ("buzzer", 0, "st1")]
    _run(go())


def test_disabled_module_drives_nothing():
    async def go():
        m, b = await _mk(enabled=False)
        await m._on_event(*_evt("run-finished", result="FAIL"))
        assert b.writes == []
    _run(go())


def test_settings_persist_and_reload():
    async def go():
        db = FakeDb()
        m, _ = await _mk(db=db)
        await m.set_config({"buzzer_enabled": False, "buzzer_duration_s": 9, "result_hold_s": 3})
        m2, _ = await _mk(db=db)                              # a fresh module on the same store
        assert (m2.buzzer_enabled, m2.buzzer_duration_s, m2.result_hold_s) == (False, 9.0, 3.0)
    _run(go())


def test_self_test_drives_one_output():
    async def go():
        m, b = await _mk()
        out = await m.self_test({"signal": "buzzer", "on": True})
        assert out["ok"] and _lit(b.writes, "buzzer", 1)
    _run(go())

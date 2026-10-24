"""debug_tool.probe - what a probe may send to an instrument, and what it must never send. Fake core with the app's real routes."""

import asyncio
import json

import httpx
import pytest

from debug_tool import probe as pr
from debug_tool.probe import InstrumentProbe, ProbeFailed, ProbeRefused
from debug_tool.tester.test_engine import make_app

CATALOG = {"capabilities": {
    "power_source": {"label": "Power source", "methods": [
        {"method": "set_voltage", "kind": "set", "args": []},
        {"method": "output_enable", "kind": "toggle", "args": []},
        {"method": "measure_voltage", "kind": "read", "args": []},
        {"method": "measure_current", "kind": "read", "args": []}]},
    "analog_input": {"label": "Analog input", "methods": [{"method": "read_voltage", "kind": "read", "args": [{"name": "channel"}]}]}},
    "base_actions": [{"method": "safe_state", "kind": "action"}, {"method": "emergency_disable", "kind": "action"}]}
INSTANCES = [{"id": "psu1", "library": "x", "capabilities": ["power_source"], "state": "connected", "simulated": True},
             {"id": "gone", "state": "skipped", "reason": "no driver"}]


class FakeCore:
    def __init__(self, values=None, fail_at=()):
        self.calls, self.values, self.fail_at, self.n = [], list(values or [5.0]), set(fail_at), 0
        self.on_call = None

    def client(self):
        def handler(req: httpx.Request) -> httpx.Response:
            if req.headers.get("authorization") != "Bearer tok":
                return httpx.Response(401, json={"detail": "bad token"})
            if req.method == "GET" and req.url.path == "/variables/instances":
                return httpx.Response(200, json=INSTANCES)
            if req.method == "GET" and req.url.path == "/variables/capabilities":
                return httpx.Response(200, json=CATALOG)
            if req.method == "POST" and req.url.path.endswith("/call"):
                body = json.loads(req.content)
                self.calls.append((req.url.path, body))
                i = self.n
                self.n += 1
                if self.on_call:
                    self.on_call(i)
                if i in self.fail_at:
                    return httpx.Response(502, json={"detail": "psu1 not reachable via the controller (timeout)"})
                return httpx.Response(200, json={"instance": "psu1", "method": body["method"], "result": self.values[i % len(self.values)]})
            return httpx.Response(404, json={"detail": "nope"})
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def make(tmp_path, core, monkeypatch=None):
    from debug_tool.engine import Engine, EngineConfig
    eng = Engine(EngineConfig(app=make_app(tmp_path), data_dir=tmp_path / "t"), http_factory=core.client)
    from debug_server.ingest import Ingestor
    eng.ingestor = Ingestor("st1")
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    clock = {"t": 1000.0}
    p = InstrumentProbe(eng, clock=lambda: clock["t"], sleep=fake_sleep)
    return eng, p, sleeps, clock


@pytest.mark.asyncio
async def test_read_methods_from_the_apps_own_catalog_are_allowed(tmp_path):
    core = FakeCore([12.3])
    eng, p, _, _ = make(tmp_path, core)
    out = await p.probe("psu1", "measure_voltage", [], "tok")
    assert out["result"] == 12.3 and out["instance"] == "psu1" and out["simulated"] is True and out["latency_ms"] >= 0
    assert core.calls == [("/variables/instances/psu1/call", {"method": "measure_voltage", "args": []})]
    assert (await p.probe("psu1", "identify", [], "tok"))["method"] == "identify"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,why", [("set_voltage", "not a read-only method"), ("output_enable", "not a read-only method"),
                                        ("safe_state", "never available"), ("emergency_disable", "never available"),
                                        ("read_voltage", "not a read-only method"),           # analog_input is not psu1's capability
                                        ("totally_made_up", "not a read-only method")])
async def test_anything_that_could_change_the_instrument_is_refused_before_it_is_sent(tmp_path, method, why):
    core = FakeCore()
    eng, p, _, _ = make(tmp_path, core)
    with pytest.raises(ProbeRefused, match=why):
        await p.probe("psu1", method, [], "tok")
    assert core.calls == []                                                    # nothing reached the app, let alone the instrument


@pytest.mark.asyncio
async def test_unknown_or_skipped_instances_and_bad_arguments_are_refused(tmp_path):
    core = FakeCore()
    eng, p, _, _ = make(tmp_path, core)
    with pytest.raises(ProbeRefused, match="known: \\['psu1', 'gone'\\]"):
        await p.probe("nope", "identify", [], "tok")
    with pytest.raises(ProbeRefused, match="skipped"):
        await p.probe("gone", "identify", [], "tok")
    with pytest.raises(ProbeRefused, match="scalars"):
        await p.probe("psu1", "measure_voltage", [{"a": 1}], "tok")
    with pytest.raises(ProbeRefused, match="scalars"):
        await p.probe("psu1", "measure_voltage", [1, 2, 3, 4, 5], "tok")
    assert core.calls == []


@pytest.mark.asyncio
async def test_a_probe_is_refused_while_a_test_run_is_active(tmp_path):
    core = FakeCore()
    eng, p, _, _ = make(tmp_path, core)
    eng.ingestor._active = True
    with pytest.raises(ProbeRefused, match="test run is in progress"):
        await p.probe("psu1", "measure_voltage", [], "tok")
    with pytest.raises(ProbeRefused, match="test run is in progress"):
        await p.poll("psu1", "measure_voltage", [], "tok")
    assert core.calls == []


@pytest.mark.asyncio
async def test_core_errors_become_structured_failures(tmp_path):
    core = FakeCore(fail_at={0})
    eng, p, _, _ = make(tmp_path, core)
    with pytest.raises(ProbeFailed, match="not reachable via the controller"):
        await p.probe("psu1", "identify", [], "tok")
    with pytest.raises(ProbeFailed, match="401"):
        await p.probe("psu1", "identify", [], "wrong")
    with pytest.raises(ProbeFailed, match="X-Core-Token"):
        await p.probe("psu1", "identify", [], None)


@pytest.mark.asyncio
async def test_calls_are_spaced_and_one_at_a_time(tmp_path):
    core = FakeCore()
    eng, p, sleeps, clock = make(tmp_path, core)
    await p.probe("psu1", "identify", [], "tok")
    await p.probe("psu1", "identify", [], "tok")                               # the fake clock did not advance: must wait
    assert sleeps and sleeps[-1] == pytest.approx(pr.PROBE_SPACING_S)
    # concurrent calls never overlap: the lock serialises them
    inflight, peak = 0, 0
    orig = eng._core

    async def slow(*a, **k):
        nonlocal inflight, peak
        if a[0] == "POST":
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.05)
            inflight -= 1
        return await orig(*a, **k)
    eng._core = slow
    await asyncio.gather(*[p.probe("psu1", "identify", [], "tok") for _ in range(4)])
    assert peak == 1


@pytest.mark.asyncio
async def test_a_hung_instrument_times_out(tmp_path, monkeypatch):
    core = FakeCore()
    eng, p, _, _ = make(tmp_path, core)
    monkeypatch.setattr(pr, "CALL_TIMEOUT_S", 0.2)
    orig = eng._core

    async def hang(method, path, token, body=None):
        if method == "POST":
            await asyncio.sleep(5)
        return await orig(method, path, token, body)
    eng._core = hang
    with pytest.raises(ProbeFailed, match="no answer from psu1 within 0.2 s"):
        await p.probe("psu1", "identify", [], "tok")


@pytest.mark.asyncio
async def test_poll_summarises_noise_latency_and_dropouts(tmp_path):
    core = FakeCore([5.0, 5.2, 4.8, 5.0], fail_at={2})
    eng, p, sleeps, _ = make(tmp_path, core)
    out = await p.poll("psu1", "measure_voltage", [], "tok", samples=5, interval_s=0.1)       # interval clamps to 0.5 s
    assert out["requested"] == 5 and out["dropouts"] == 1 and out["ok_samples"] == 4 and out["dropout_detail"][0]["sample"] == 2
    assert out["stats"]["min"] == 5.0 and out["stats"]["max"] == 5.2                            # call order; sample 2 dropped
    assert out["stats"]["n"] == 4 and out["latency_ms"]["max"] >= out["latency_ms"]["p50"]
    assert all(s >= pr.MIN_SPACING_S - 1e-9 for s in sleeps)


@pytest.mark.asyncio
async def test_poll_is_capped_and_non_numeric_results_get_a_note(tmp_path):
    core = FakeCore(["PSU-1234"])
    eng, p, _, _ = make(tmp_path, core)
    out = await p.poll("psu1", "identify", [], "tok", samples=999, interval_s=0.5)
    assert out["requested"] == pr.MAX_SAMPLES and "not numeric" in out["note"] and "stats" not in out


@pytest.mark.asyncio
async def test_poll_stops_the_moment_a_test_run_starts(tmp_path):
    core = FakeCore([1.0])
    eng, p, _, _ = make(tmp_path, core)
    core.on_call = lambda i: setattr(eng.ingestor, "_active", i >= 1)           # a run begins after the second sample
    out = await p.poll("psu1", "measure_voltage", [], "tok", samples=10, interval_s=0.5)
    assert out["ok_samples"] == 2 and "test run started" in out["stopped_early"]


@pytest.mark.asyncio
async def test_poll_respects_its_time_budget(tmp_path, monkeypatch):
    core = FakeCore([1.0])
    eng, p, _, clock = make(tmp_path, core)
    monkeypatch.setattr(pr, "MAX_POLL_BUDGET_S", 5.0)
    core.on_call = lambda i: clock.__setitem__("t", clock["t"] + 3.0)
    out = await p.poll("psu1", "measure_voltage", [], "tok", samples=20, interval_s=1.0)
    assert out["ok_samples"] < 20 and "time budget" in out["stopped_early"]

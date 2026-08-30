"""tmf-debug client + CLI tests — self-contained (a stub sidecar app via ASGITransport,
no backend import, no network)."""

import json

import httpx

from tmf_debug import cli
from tmf_debug.client import DebugClient

REC = [
    {"seq": 1, "level": "info", "subsystem": "daq",
     "payload": {"type": "run-started", "payload": {"run_id": "R1"}}},
    {"seq": 2, "level": "error", "subsystem": "daq",
     "payload": {"type": "test-result", "payload": {"run_id": "R1"}}},
    {"seq": 3, "level": "info", "subsystem": "runs",
     "payload": {"type": "run-started", "payload": {"run_id": "R2"}}},
]


def _client(events):
    """A DebugClient wired to a sync MockTransport standing in for the sidecar."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/debug/health":
            return httpx.Response(200, json={"buffer_used": len(events), "dropped": 0, "station": "st1"})
        if request.url.path == "/debug/events":
            return httpx.Response(200, json=events)
        return httpx.Response(404, json={"detail": "not found"})

    return DebugClient("bench", transport=httpx.MockTransport(handler))


def test_health_and_events():
    c = _client(REC)
    assert c.health()["station"] == "st1"
    assert len(c.events()) == 3


def test_run_id_extraction():
    assert cli._run_id_of(REC[0]) == "R1"
    assert cli._run_id_of(REC[2]) == "R2"
    assert cli._run_id_of({"payload": {"foo": 1}}) is None


def test_pull_last_run_writes_only_that_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_client", lambda args: _client(REC))
    rc = cli.main(["pull", "--host", "bench", "--last-run"])
    assert rc == 0
    out = tmp_path / ".debug" / "bench-R2.jsonl"
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["seq"] == 3


def test_pull_specific_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_client", lambda args: _client(REC))
    rc = cli.main(["pull", "--host", "bench", "--run", "R1"])
    assert rc == 0
    out = tmp_path / ".debug" / "bench-R1.jsonl"
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert {json.loads(x)["seq"] for x in lines} == {1, 2}

"""tmf_debug.api (why / select_run, shared with the Debug Tool + MCP) and tmf_debug.instrument (passive history)."""

import json

import httpx

from tmf_debug import api, cli
from tmf_debug.client import DebugClient
from tmf_debug.instrument import instrument_digest


def rec(ts, **kw):
    return {"seq": int(ts * 10), "ts": ts, "station": "st1", **kw}


def event(ts, etype, run):
    return rec(ts, kind="event", type=etype, payload={"type": etype, "ts": ts, "payload": {"run_id": run}})


def diag(ts, level, sub, message, **ctx):
    return rec(ts, kind="diag", subsystem=sub, level=level, message=message,
               payload={"ts": ts, "level": level, "subsystem": sub, "message": message, "context": ctx})


RUN = [event(1.0, "run-started", "R9"),
       diag(1.5, "error", "instrument", "psu1.measure_voltage timeout: no reply",
            instance_id="psu1", method="measure_voltage", outcome="timeout", elapsed_ms=2000.0, args="(1,)",
            error={"type": "CommandTimeout", "message": "no reply in 2 s", "cause": "OSError: link dropped", "traceback_tail": ["a.py:1 in f"]}),
       event(3.0, "run-finished", "R9")]


def test_why_writes_raw_and_digest_and_returns_the_first_fault(tmp_path):
    out = api.why(RUN, out_dir=tmp_path, prefix="bench1", last=True)
    assert out["run"] == "R9" and out["records"] == 3
    assert (tmp_path / "bench1-R9.jsonl").is_file() and (tmp_path / "bench1-R9.digest.json").is_file()
    assert out["first_fault"] is not None and out["fault_count"] >= 1


def test_why_with_no_records_is_none(tmp_path):
    assert api.why([], out_dir=tmp_path, prefix="b") is None


def test_the_cli_still_exposes_the_old_private_names():
    assert cli._run_id_of is api.run_id_of and cli._select_run is api.select_run


def test_cli_why_uses_the_library(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def handler(request):
        return httpx.Response(200, json=RUN)
    monkeypatch.setattr(cli, "_client", lambda args: DebugClient("bench", transport=httpx.MockTransport(handler)))
    assert cli.main(["why", "--host", "bench"]) == 0
    assert "digest:" in capsys.readouterr().out and (tmp_path / ".debug" / "bench-R9.digest.json").is_file()


# ---- instrument digest -------------------------------------------------------------------------

STREAM = [
    diag(1.0, "info", "instrument", "measure_voltage", instance_id="psu1", method="measure_voltage", outcome="ok",
         elapsed_ms=10.0, args="(1,)"),
    diag(1.1, "info", "instrument", "measure_voltage", instance_id="psu1", method="measure_voltage", outcome="ok",
         elapsed_ms=30.0),
    diag(2.0, "warning", "instrument", "psu1 link reconnecting", instance_id="psu1", state="reconnecting"),
    diag(2.5, "info", "instrument", "psu1 link connected", instance_id="psu1", state="connected"),
    diag(3.0, "error", "instrument", "psu1.set_voltage error: boom", instance_id="psu1", method="set_voltage", outcome="error",
         elapsed_ms=5.0, error={"type": "DeviceError", "message": "boom", "cause": "ValueError: x", "traceback_tail": ["x.py:2 in g"]}),
    diag(4.0, "warning", "instrument", "dmm1 link faulted", instance_id="dmm1", state="faulted"),
    diag(5.0, "info", "daq", "unrelated", instance_id="psu1"),             # other subsystem: ignored
]


def test_instrument_digest_state_timeline_counts_and_latency():
    d = instrument_digest(STREAM)
    psu = d["instruments"]["psu1"]
    assert [t["state"] for t in psu["state_timeline"]] == ["reconnecting", "connected"]
    assert psu["state"] == "connected" and psu["drops"] == 1
    mv = psu["methods"]["measure_voltage"]
    assert mv["calls"] == 2 and mv["failed"] == 0 and mv["latency_ms"]["max"] == 30.0
    assert psu["methods"]["set_voltage"]["failed"] == 1 and psu["failed_calls"] == 1
    assert psu["recent_failures"][0]["cause"] == "ValueError: x" and psu["recent_failures"][0]["traceback_tail"] == ["x.py:2 in g"]
    assert d["instruments"]["dmm1"]["state"] == "faulted"
    assert d["instrument_events"] == 6 and "under-report" in d["coverage"]


def test_instrument_digest_filters_one_instance_and_handles_no_events():
    d = instrument_digest(STREAM, instance_id="dmm1")
    assert list(d["instruments"]) == ["dmm1"]
    assert instrument_digest([])["instruments"] == {} and instrument_digest([])["time_range"] is None


def test_instance_id_falls_back_to_the_message_when_the_context_is_missing():
    r = rec(1.0, kind="diag", subsystem="instrument", level="warning", message="ni1 link disconnected",
            payload={"context": {"state": "disconnected"}})
    assert list(instrument_digest([r])["instruments"]) == ["ni1"]


def test_failures_list_is_capped_to_the_most_recent():
    many = [diag(float(i), "error", "instrument", "x.m error: e", instance_id="x", method="m", outcome="error", elapsed_ms=1.0)
            for i in range(30)]
    d = instrument_digest(many, max_failures=5)["instruments"]["x"]
    assert len(d["recent_failures"]) == 5 and d["recent_failures"][-1]["ts"] == 29.0 and d["failed_calls"] == 30


def test_cli_instrument_command(monkeypatch, capsys):
    def handler(request):
        assert request.url.params.get("subsystem") == "instrument"
        return httpx.Response(200, json=STREAM)
    monkeypatch.setattr(cli, "_client", lambda args: DebugClient("bench", transport=httpx.MockTransport(handler)))
    assert cli.main(["instrument", "--host", "bench", "--id", "psu1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out["instruments"]) == ["psu1"]

"""digest golden test (REMOTE_DEBUG.md §9) — a synthetic capture with a first fault,
warnings, a stuck command, a schema violation, analog values, and digital edges."""

import json

from tmf_debug.digest import digest_file, digest_records

CAPTURE = [
    # run start (carries version metadata for the header)
    {"seq": 1, "ts": 100.0, "kind": "event", "type": "run-started", "station": "st1",
     "trace": "run:R1", "payload": {"type": "run-started", "ts": 100.0,
                                    "payload": {"run_id": "R1", "app_version": "1.2.0",
                                                "source_version": "1.1.0"}}},
    # analog values (a flat rail then a drop) + a boolean toggle
    {"seq": 2, "ts": 100.1, "kind": "value", "subtopic": "value/vbus", "station": "st1",
     "payload": {"name": "vbus", "value": 12.0}},
    {"seq": 3, "ts": 100.6, "kind": "value", "subtopic": "value/vbus", "station": "st1",
     "payload": {"name": "vbus", "value": 9.5}},
    {"seq": 4, "ts": 100.2, "kind": "value", "subtopic": "value/relay", "station": "st1",
     "payload": {"name": "relay", "value": False}},
    {"seq": 5, "ts": 100.7, "kind": "value", "subtopic": "value/relay", "station": "st1",
     "payload": {"name": "relay", "value": True}},
    # info + a warning (warning is included verbatim; info only counted)
    {"seq": 6, "ts": 100.3, "kind": "diag", "subsystem": "daq", "level": "info",
     "message": "ai stream start", "station": "st1", "payload": {"context": {}}},
    {"seq": 7, "ts": 100.4, "kind": "diag", "subsystem": "daq", "level": "warning",
     "message": "clamp applied", "station": "st1", "trace": "run:R1",
     "payload": {"context": {"name": "vbus"}}},
    # a stuck command: request with no reply
    {"seq": 8, "ts": 100.45, "kind": "request", "corr_id": "c1", "type": "dut.power_on",
     "topic": "tmf/st1/cmd/dut.power_on", "station": "st1", "payload": {"id": "c1"}},
    # THE first fault: an error diag (earliest fault by ts)
    {"seq": 9, "ts": 100.42, "kind": "diag", "subsystem": "controller", "level": "error",
     "message": "AC-OK never asserted", "station": "st1", "trace": "run:R1",
     "payload": {"context": {"step": "acw"}}},
    # a schema violation
    {"seq": 10, "ts": 100.5, "kind": "diag", "subsystem": "runs", "valid": False,
     "topic": "tmf/st1/diag/runs", "type": "diag", "error": "missing 'message'",
     "station": "st1", "payload": {"level": "info"}},
    # a failing test-result (also a fault, but later than the error diag)
    {"seq": 11, "ts": 100.8, "kind": "event", "type": "test-result", "station": "st1",
     "trace": "run:R1", "payload": {"type": "test-result", "ts": 100.8,
                                    "payload": {"run_id": "R1", "test_name": "ACW",
                                                "result": "FAIL", "measured": 0.0,
                                                "limits": {"min": 1}}}},
]


def test_digest_shape_and_first_fault():
    d = digest_records(CAPTURE, meta={"host": "bench1", "dropped": 0, "suppressed": 3})

    # header self-describing
    h = d["header"]
    assert h["station"] == "st1"
    assert h["app_version"] == "1.2.0" and h["framework_version"] == "1.1.0"
    assert h["host"] == "bench1"
    assert h["time_range"][0] == 100.0
    assert h["completeness"] == {"dropped": 0, "suppressed": 3, "snapshots_suppressed": 0}

    # first_fault is the EARLIEST fault — the error diag at ts 100.42, not the later FAIL
    ff = d["first_fault"]
    assert ff["category"] == "error_diag" and ff["ts"] == 100.42
    assert ff["message"] == "AC-OK never asserted"

    # faults include the stuck command and the failing step too
    cats = {f["category"] for f in d["faults"]}
    assert {"error_diag", "stuck_command", "step_failure"} <= cats
    stuck = d["stuck_commands"][0]
    assert stuck["corr_id"] == "c1" and stuck["req_topic"].endswith("dut.power_on")

    # warnings verbatim; info/debug only counted
    assert any(w["message"] == "clamp applied" for w in d["warnings"])
    assert not any(w["message"] == "ai stream start" for w in d["warnings"])
    counted = {(x["subsystem"], x["message"]): x["count"]
               for x in d["summary"]["info_debug_by_subsystem_message"]}
    assert counted[("daq", "ai stream start")] == 1

    # schema violation surfaced
    assert d["schema_violations"][0]["error"] == "missing 'message'"

    # analog summarised; digital transition counted
    assert d["summary"]["analog"]["vbus"] == {"min": 9.5, "max": 12.0, "avg": 10.75, "n": 2}
    assert d["summary"]["digital_transitions"]["relay"] == 1

    # error trace waterfall present for the run that had an error
    assert "run:R1" in d["error_trace_waterfalls"]


def test_digest_file_roundtrip_and_size(tmp_path):
    cap = tmp_path / "bench1-R1.jsonl"
    with cap.open("w", encoding="utf-8") as fh:
        for rec in CAPTURE:
            fh.write(json.dumps(rec) + "\n")
        fh.write(json.dumps({"__meta__": {"suppressed": 5}}) + "\n")

    out = digest_file(cap)
    assert out.name == "bench1-R1.digest.json"
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["first_fault"]["category"] == "error_diag"
    assert d["header"]["source_file"] == "bench1-R1.jsonl"
    assert d["header"]["source_bytes"] > 0
    assert d["header"]["completeness"]["suppressed"] == 5      # from the __meta__ line
    assert len(out.read_text(encoding="utf-8").encode("utf-8")) <= 100 * 1024

"""tmf_debug.bundle - read an offline diagnostics bundle back into analysis.md / analysis.json."""

import json
import zipfile
from pathlib import Path

import pytest

from tmf_debug import bundle, cli


def rec(ts, **kw):
    return {"seq": int(ts * 10), "ts": ts, "station": "st1", **kw}


def diag(ts, level, sub, msg, **ctx):
    return rec(ts, kind="diag", subsystem=sub, level=level, message=msg,
               payload={"ts": ts, "level": level, "subsystem": sub, "message": msg, "context": ctx})


def ev(ts, etype, run, **extra):
    return rec(ts, kind="event", type=etype, payload={"type": etype, "ts": ts, "payload": {"run_id": run, **extra}})


RECORDER = [ev(1.0, "run-started", "R7", app_version="2.0.0"),
            diag(1.5, "error", "instrument", "psu1.measure_voltage timeout: no reply", instance_id="psu1",
                 method="measure_voltage", outcome="timeout", elapsed_ms=2000.0,
                 error={"type": "CommandTimeout", "message": "no reply in 2 s", "cause": "OSError", "traceback_tail": ["a.py:1 in f"]}),
            diag(1.6, "warning", "instrument", "psu1 link faulted", instance_id="psu1", state="faulted"),
            ev(3.0, "run-finished", "R7")]


def make_bundle(path: Path, *, recorder=True, controllers=1, broker="mosquitto.exe", integrity="ok", odbc=("SQL Server",),
                provider="sqlserver", running=True, missing=(), script=None) -> Path:
    files = {
        "MANIFEST.json": json.dumps({"files": [], "missing": list(missing)}),
        "environment.json": json.dumps({"exported_at": "2026-10-20T10:00:00", "platform": "Windows-11", "frozen": True,
                                        "framework_version": "1.32.0", "app_version": "2.0.0", "state_root": "D:/deploy"}),
        "config/app.json": json.dumps({"controller": {"kind": "python"}, "stations": ["st1"],
                                       "modules": [{"id": "report", "config": {"db": {"provider": provider}}}]}),
        "logs/error_log.jsonl": "\n".join(json.dumps({"ts": float(i), "summary": "s", "data": {"level": "error", "subsystem": "x",
                                                      "message": "boom" if i % 2 else "bang"}}) for i in range(6)) + "\n",
        "logs/action_log.jsonl": json.dumps({"ts": 1.0, "summary": "login", "data": {"action": "auth.login"}}) + "\n",
        "logs/launcher.log": "ok\nswap FAILED: [WinError 5] Access is denied\nrelaunch\n",
        "system/processes.json": json.dumps({"processes": [
            {"pid": 1, "name": "run.exe", "cmdline": "run.exe --controller x.json"},
            *[{"pid": 10 + i, "name": "run.exe", "cmdline": "run.exe --controller y.json"} for i in range(controllers - 1)]]}),
        "system/ports.json": json.dumps({"ports": {"1883": {"listening": True, "pid": 5, "name": broker},
                                                   "8000": {"listening": running}}}),
        "system/odbc.json": json.dumps({"drivers": list(odbc)}),
        "system/health.json": json.dumps({"app_running": running, "readyz": {"status": 200, "body": {"ready": True}}}
                                         if running else {"app_running": False, "note": "did not answer"}),
        "install/integrity.json": json.dumps({"status": integrity, "modified": ["run.dist/run.exe"] if integrity == "MISMATCH" else [],
                                              "missing": [], "note": "half-applied update"}),
    }
    if recorder:
        files["diagnostics/rolling.jsonl"] = "\n".join(json.dumps(r) for r in RECORDER) + "\n"
    if script:
        files["script/output.txt"] = script["out"]
        files["script/result.json"] = json.dumps({"exit_code": script["rc"]})
    with zipfile.ZipFile(path, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
    return path


def titles(a):
    return [f["title"] for f in a["findings"]]


def test_a_healthy_bundle_still_reports_the_first_fault_and_writes_the_files(tmp_path):
    z = make_bundle(tmp_path / "b.zip")
    a = bundle.analyze(z, tmp_path / "out", name="bench1")
    assert Path(a["paths"]["analysis_md"]).is_file() and Path(a["paths"]["analysis_json"]).is_file()
    assert a["recorder"]["first_fault"] is not None and a["recorder"]["records"] == 4
    md = Path(a["paths"]["analysis_md"]).read_text(encoding="utf-8")
    assert "Look here first" in md and "Flight recorder" in md and "psu1" in md
    assert json.loads(Path(a["paths"]["analysis_json"]).read_text())["schema"] == "tmf-debug/bundle-analysis/1"
    assert Path(a["paths"]["digest"]).is_file()


def test_instrument_table_is_built_from_recorder_and_flagged(tmp_path):
    a = bundle.analyze(make_bundle(tmp_path / "b.zip"), tmp_path / "out")
    psu = a["instruments"]["instruments"]["psu1"]
    assert psu["state"] == "faulted" and psu["failed_calls"] == 1 and psu["recent_failures"][0]["cause"] == "OSError"
    assert any("psu1 ended in state 'faulted'" in t for t in titles(a))


def test_second_controller_foreign_broker_and_integrity_mismatch_are_findings(tmp_path):
    z = make_bundle(tmp_path / "b.zip", controllers=2, broker="python.exe", integrity="MISMATCH")
    a = bundle.analyze(z, tmp_path / "out")
    t = " | ".join(titles(a))
    assert "2 controller processes" in t and ":1883 is held by python.exe" in t and "installed files differ" in t
    assert [f["severity"] for f in a["findings"]] == sorted((f["severity"] for f in a["findings"]),
                                                            key=lambda s: bundle.SEV_ORDER[s])     # worst first
    assert a["look_here_first"][0].startswith("[error]")


def test_app_not_running_and_no_broker(tmp_path):
    z = make_bundle(tmp_path / "b.zip", running=False)
    z2 = tmp_path / "nb.zip"
    with zipfile.ZipFile(z) as src, zipfile.ZipFile(z2, "w") as dst:
        for n in src.namelist():
            data = src.read(n)
            if n == "system/ports.json":
                data = json.dumps({"ports": {"1883": {"listening": False}, "8000": {"listening": False}}}).encode()
            dst.writestr(n, data)
    t = titles(bundle.analyze(z2, tmp_path / "out"))
    assert any("not running" in x for x in t) and any("nothing is listening on :1883" in x for x in t)


def test_sql_server_report_db_without_an_odbc_driver_is_flagged(tmp_path):
    a = bundle.analyze(make_bundle(tmp_path / "b.zip", odbc=()), tmp_path / "out")
    assert any("no SQL Server ODBC driver" in t for t in titles(a))
    ok = bundle.analyze(make_bundle(tmp_path / "ok.zip", provider="mysql", odbc=()), tmp_path / "out2")
    assert not any("ODBC" in t for t in titles(ok))


def test_empty_recorder_and_missing_items_are_called_out_not_hidden(tmp_path):
    z = make_bundle(tmp_path / "b.zip", recorder=False, missing=("diagnostics/ (never enabled)",))
    a = bundle.analyze(z, tmp_path / "out")
    t = titles(a)
    assert any("holds no records" in x for x in t) and any("could not be collected" in x for x in t)
    assert a["recorder"]["first_fault"] is None and a["manifest_missing"] == ["diagnostics/ (never enabled)"]


def test_error_log_summary_and_launcher_highlights(tmp_path):
    a = bundle.analyze(make_bundle(tmp_path / "b.zip"), tmp_path / "out")
    assert any("6 error_log row(s)" in t for t in titles(a))
    assert len(a["recent_errors"]) == 6 and any("swap FAILED" in ln for ln in a["launcher_highlights"])


def test_script_kit_output_is_appended_to_the_analysis(tmp_path):
    a = bundle.analyze(make_bundle(tmp_path / "b.zip", script={"out": "Get-NetTCPConnection...\nstray listener", "rc": 3}), tmp_path / "out")
    assert a["script"]["result"]["exit_code"] == 3 and "stray listener" in a["script"]["output_tail"]
    assert any("script exited 3" in t for t in titles(a))
    assert "Script output" in Path(a["paths"]["analysis_md"]).read_text(encoding="utf-8")


def test_zip_slip_is_refused_and_nothing_is_written_outside(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escaped.txt", "x")
    with pytest.raises(bundle.BundleError, match="unsafe path"):
        bundle.analyze(z, tmp_path / "out")
    assert not (tmp_path / "escaped.txt").exists()


def test_not_a_zip_and_missing_file_are_clear_errors(tmp_path):
    (tmp_path / "x.zip").write_text("nope")
    with pytest.raises(bundle.BundleError, match="not a zip"):
        bundle.analyze(tmp_path / "x.zip", tmp_path)
    with pytest.raises(bundle.BundleError, match="no such bundle"):
        bundle.analyze(tmp_path / "nothing.zip", tmp_path)


def test_a_malformed_member_never_aborts_the_analysis(tmp_path):
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("MANIFEST.json", "{not json")
        zf.writestr("environment.json", "[]")
        zf.writestr("diagnostics/rolling.jsonl", "garbage\n{\"ts\": 1}\n")
        zf.writestr("system/processes.json", "nope")
    a = bundle.analyze(z, tmp_path / "out")
    assert a["schema"] == "tmf-debug/bundle-analysis/1"


def test_cli_analyze(tmp_path, capsys):
    z = make_bundle(tmp_path / "b.zip", controllers=2)
    assert cli.main(["analyze", str(z), "--out", str(tmp_path / "o"), "--name", "bench9"]) == 0
    out = capsys.readouterr().out
    assert "analysis.md" in out and "controller" in out
    assert cli.main(["analyze", str(tmp_path / "missing.zip"), "--out", str(tmp_path / "o")]) == 2


def test_the_real_export_bundle_round_trips_through_the_analyser(tmp_path, monkeypatch):
    """Whatever debug_server.export writes, the analyser must be able to read (guards the two against drifting)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from debug_server import sysinfo
    from debug_server.export import export_bundle
    state = tmp_path / "state"
    (state / "config").mkdir(parents=True)
    (state / "data" / "debug").mkdir(parents=True)
    (state / "config" / "app.json").write_text(json.dumps({"stations": ["st1"], "controller": {"kind": "python"}}))
    (state / "data" / "debug" / "rolling.jsonl").write_text("\n".join(json.dumps(r) for r in RECORDER) + "\n")
    monkeypatch.setattr(sysinfo, "processes", lambda: {"processes": []})
    monkeypatch.setattr(sysinfo, "app_health", lambda port=None: {"app_running": False, "note": "n"})
    out = tmp_path / "real.zip"
    export_bundle(out, state_root=state, integrity=False)
    a = bundle.analyze(out, tmp_path / "o")
    assert a["recorder"]["records"] == 4 and a["instruments"]["instruments"]["psu1"]["failed_calls"] == 1

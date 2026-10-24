"""Export v2 (v1.32.0): system facts + install integrity + instrument events in the offline bundle.
Everything is read-only and none of it may fail the export."""

import gzip
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from debug_server import sysinfo
from debug_server.export import _instrument_events, export_bundle


def _state(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "data" / "debug").mkdir(parents=True)
    (tmp_path / "config" / "app.json").write_text(json.dumps({"stations": ["st1"]}))
    con = sqlite3.connect(tmp_path / "data" / "tmf.sqlite")
    con.execute("CREATE TABLE records (id TEXT, type TEXT, ts REAL, station TEXT, source_version TEXT, summary TEXT, data TEXT, "
                "PRIMARY KEY (type, id))")
    con.commit()
    con.close()
    return tmp_path


def _fast(monkeypatch):
    """No PowerShell/netstat/HTTP in unit tests."""
    monkeypatch.setattr(sysinfo, "processes", lambda: {"processes": [{"pid": 1, "name": "run.exe", "cmdline": "run.exe"}]})
    monkeypatch.setattr(sysinfo, "ports", lambda procs=None: {"ports": {"8000": {"listening": True, "pid": 1}}})
    monkeypatch.setattr(sysinfo, "odbc_drivers", lambda: {"drivers": ["SQL Server"]})
    monkeypatch.setattr(sysinfo, "app_health", lambda port=None: {"app_running": False, "note": "x"})


def _install(tmp_path, files):
    """deploy/run.dist/<files> + RELEASE.json with the real build_release.manifest() shape (keys relative to deploy/)."""
    deploy = tmp_path / "deploy"
    dist = deploy / "run.dist"
    table = {}
    for rel, data in files.items():
        p = deploy / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        table[rel] = hashlib.sha256(data).hexdigest()
    (dist / "RELEASE.json").write_text(json.dumps({"product": "acme", "version": "2.0.0", "framework_version": "1.32.0",
                                                   "sha256": table}))
    return dist


def _read(out, name):
    return json.loads(zipfile.ZipFile(out).read(name))


def test_bundle_has_the_new_system_files_and_never_lists_them_as_missing(tmp_path, monkeypatch):
    _fast(monkeypatch)
    st = _state(tmp_path / "s")
    out = tmp_path / "b.zip"
    m = export_bundle(out, state_root=st)
    names = set(zipfile.ZipFile(out).namelist())
    assert {"system/processes.json", "system/ports.json", "system/odbc.json", "system/health.json", "install/integrity.json"} <= names
    assert _read(out, "system/odbc.json")["drivers"] == ["SQL Server"]
    assert all("system/" not in x and "install/" not in x for x in m["missing"])      # facts degrade to notes, not "missing"


def test_integrity_ok_modified_and_missing_files(tmp_path, monkeypatch):
    _fast(monkeypatch)
    dist = _install(tmp_path, {"run.dist/run.exe": b"EXE", "run.dist/lib/a.pyd": b"A", "run_station.exe": b"RS"})
    st = _state(tmp_path / "s")
    out = tmp_path / "ok.zip"
    export_bundle(out, state_root=st, bundle_root_override=dist)
    ok = _read(out, "install/integrity.json")
    assert ok["status"] == "ok" and ok["checked"] == 3 and ok["version"] == "2.0.0"

    (dist / "lib" / "a.pyd").write_bytes(b"TAMPERED")            # half-applied update / AV rewrote it
    (dist.parent / "run_station.exe").unlink()
    out2 = tmp_path / "bad.zip"
    export_bundle(out2, state_root=st, bundle_root_override=dist)
    bad = _read(out2, "install/integrity.json")
    assert bad["status"] == "MISMATCH" and bad["modified"] == ["run.dist/lib/a.pyd"] and bad["missing"] == ["run_station.exe"]
    assert "half-applied" in bad["note"]


def test_integrity_unavailable_without_a_release_manifest_and_skippable(tmp_path, monkeypatch):
    _fast(monkeypatch)
    st = _state(tmp_path / "s")
    out = tmp_path / "src.zip"
    export_bundle(out, state_root=st, bundle_root_override=tmp_path)             # no RELEASE.json here
    assert _read(out, "install/integrity.json")["status"] == "unavailable"
    dist = _install(tmp_path / "i", {"run.dist/run.exe": b"E"})
    out2 = tmp_path / "skip.zip"
    export_bundle(out2, state_root=st, bundle_root_override=dist, integrity=False)
    assert _read(out2, "install/integrity.json")["status"] == "skipped"


def test_integrity_has_a_time_budget(tmp_path):
    dist = _install(tmp_path, {f"run.dist/f{i}.bin": b"x" * 10 for i in range(5)})
    res = sysinfo.integrity(dist, budget_s=-1)                                   # already out of budget
    assert res["truncated"] is True and res["status"] == "incomplete" and res["checked"] == 0


def test_instrument_events_extracted_from_plain_and_gzipped_recorder_files(tmp_path):
    d = tmp_path / "debug"
    d.mkdir()
    inst = json.dumps({"subsystem": "instrument", "level": "error", "message": "psu1.set_voltage error: x", "ts": 1.0})
    mention = json.dumps({"subsystem": "daq", "message": "talks about \"instrument\" only", "ts": 2.0})
    (d / "rolling.jsonl").write_text(inst + "\n" + mention + "\nnot json at all \"instrument\"\n", encoding="utf-8")
    with gzip.open(d / "old.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"subsystem": "instrument", "message": "ni1 link faulted", "ts": 0.5}) + "\n")
    got = [json.loads(x)["message"] for x in _instrument_events(d)]
    assert sorted(got) == ["ni1 link faulted", "psu1.set_voltage error: x"]


def test_instrument_events_file_lands_in_the_bundle(tmp_path, monkeypatch):
    _fast(monkeypatch)
    st = _state(tmp_path / "s")
    (st / "data" / "debug" / "rolling.jsonl").write_text(
        json.dumps({"subsystem": "instrument", "message": "m", "ts": 1}) + "\n", encoding="utf-8")
    out = tmp_path / "b.zip"
    export_bundle(out, state_root=st)
    assert zipfile.ZipFile(out).read("logs/instrument_events.jsonl").decode().count("\n") == 1


def test_a_probe_that_cannot_run_degrades_to_a_note_instead_of_failing_the_export(tmp_path, monkeypatch):
    monkeypatch.setattr(sysinfo, "_run", lambda cmd, timeout=20: (1, "boom"))
    st = _state(tmp_path / "s")
    out = tmp_path / "b.zip"
    export_bundle(out, state_root=st)                                            # must not raise
    assert "error" in _read(out, "system/processes.json") or _read(out, "system/processes.json")["processes"] == []
    assert _read(out, "system/health.json")["app_running"] is False and "note" in _read(out, "system/health.json")


def test_app_health_reports_a_running_app(monkeypatch):
    answers = {"/healthz": {"status": 200, "body": {"status": "ok"}}, "/readyz": {"status": 200, "body": {"ready": True}},
               "/modules/status": {"status": 401, "error": "HTTP 401"}}
    monkeypatch.setattr(sysinfo, "_get", lambda url, timeout=2.5: answers[url.split("8000", 1)[1]])
    h = sysinfo.app_health(8000)
    assert h["app_running"] is True and h["readyz"]["body"]["ready"] is True and "note" not in h


def test_ports_name_the_process_holding_each_port(monkeypatch):
    monkeypatch.setattr(sysinfo.sys, "platform", "win32")
    netstat = ("  TCP    127.0.0.1:1883    0.0.0.0:0    LISTENING    4242\n  TCP    0.0.0.0:8001    0.0.0.0:0    LISTENING    77\n"
               "  TCP    0.0.0.0:9999    0.0.0.0:0    LISTENING    5\n")
    monkeypatch.setattr(sysinfo, "_run", lambda cmd, timeout=20: (0, netstat))
    procs = {"processes": [{"pid": 4242, "name": "mosquitto.exe", "cmdline": "mosquitto -c x"}]}
    res = sysinfo.ports(procs)["ports"]
    assert res["1883"]["listening"] and res["1883"]["name"] == "mosquitto.exe"
    assert res["8001"]["listening"] and res["8001"]["pid"] == 77 and res["8001"].get("name") is None
    assert res["8000"]["listening"] is False and "9999" not in res


@pytest.mark.skipif(not Path("C:/Windows").exists(), reason="Windows-only smoke test")
def test_real_processes_probe_returns_this_python():
    res = sysinfo.processes()
    assert "processes" in res and any("python" in p["name"].lower() for p in res["processes"])

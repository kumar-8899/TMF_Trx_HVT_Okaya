"""Offline diagnostics export (FRAMEWORK CR A2) + the frozen-safe path helpers (B5)."""

import json
import sqlite3
import zipfile

from core import paths
from debug_server.export import _redact, export_bundle


def _station(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "data" / "debug").mkdir(parents=True)
    (tmp_path / "config" / "app.json").write_text(json.dumps(
        {"stations": ["st1"], "report": {"db": {"host": "h", "password": "hunter2"}}, "mes": {"token": "abc"}}))
    (tmp_path / "data" / "controller.generated.json").write_text(json.dumps({"broker": {"host": "127.0.0.1"}}))
    (tmp_path / "data" / "debug" / "debug.jsonl").write_text('{"seq":1}\n')
    con = sqlite3.connect(tmp_path / "data" / "tmf.sqlite")
    con.execute("CREATE TABLE records (id TEXT, type TEXT, ts REAL, station TEXT, source_version TEXT, "
                "summary TEXT, data TEXT, PRIMARY KEY (type, id))")
    for i in range(3):
        con.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?)",
                    (f"e{i}", "error_log", float(i), "st1", "1", f"s{i}", json.dumps({"message": f"m{i}"})))
    con.execute("INSERT INTO records VALUES ('a0','action_log',1.0,'st1','1','x','{\"action\":\"auth.login\"}')")
    con.commit()
    con.close()


def test_export_packs_recorder_logs_config_and_environment(tmp_path):
    _station(tmp_path)
    out = tmp_path / "out" / "bundle.zip"
    m = export_bundle(out, state_root=tmp_path)
    z = zipfile.ZipFile(out)
    names = set(z.namelist())
    assert {"diagnostics/debug.jsonl", "logs/error_log.jsonl", "logs/action_log.jsonl", "config/app.json",
            "config/controller.generated.json", "environment.json", "MANIFEST.json"} <= names
    errs = [json.loads(line) for line in z.read("logs/error_log.jsonl").decode().splitlines()]
    assert [e["data"]["message"] for e in errs] == ["m0", "m1", "m2"]            # oldest -> newest
    cfg = z.read("config/app.json").decode()
    assert "hunter2" not in cfg and "abc" not in cfg and "redacted" in cfg        # secrets never leave the PC
    assert m["missing"] == [] or all("launcher.log" in x for x in m["missing"])


def test_export_reports_what_is_missing_instead_of_an_empty_zip(tmp_path):
    out = tmp_path / "b.zip"
    m = export_bundle(out, state_root=tmp_path)        # a state dir with nothing in it
    assert any("Remote debugging" in x for x in m["missing"])
    assert any("tmf.sqlite" in x for x in m["missing"])
    assert "MANIFEST.json" in zipfile.ZipFile(out).namelist()


def test_export_never_modifies_the_station_db(tmp_path):
    _station(tmp_path)
    db = tmp_path / "data" / "tmf.sqlite"
    before = db.read_bytes()
    export_bundle(tmp_path / "b.zip", state_root=tmp_path)
    assert db.read_bytes() == before


def test_redact_is_recursive():
    assert _redact({"a": [{"api_key": "k", "ok": 1}]}) == {"a": [{"api_key": "***redacted***", "ok": 1}]}


def test_bundle_root_source_is_repo_and_env_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("TMF_BUNDLE_DIR", raising=False)
    assert (paths.bundle_root() / "backend" / "core").is_dir()                    # source: the repo root
    monkeypatch.setenv("TMF_BUNDLE_DIR", str(tmp_path))
    assert paths.bundle_root() == tmp_path
    assert paths.bundle_path("app/x/maps/st1.json") == tmp_path / "app/x/maps/st1.json"


def test_bundle_root_frozen_is_the_exe_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("TMF_BUNDLE_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(tmp_path / "run.exe"))
    assert paths.is_frozen() and paths.bundle_root() == tmp_path.resolve()


def test_load_failed_is_an_error_with_the_path_tried(tmp_path):
    events = []
    from core.services.diagnostics import Diagnostics
    diag = Diagnostics("st1", "0", sinks=[events.append])
    paths.load_failed(diag, "okaya", "signal map", tmp_path / "nope.json", FileNotFoundError("nope"))
    (ev,) = [e for e in events if e["subsystem"] == "okaya"]
    assert ev["level"] == "error" and ev["context"]["exists"] is False and "nope.json" in ev["context"]["path"]

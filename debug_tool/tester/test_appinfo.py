"""debug_tool.appinfo - finding the app install and reading the documented files (read-only)."""

import json

from debug_tool import appinfo


def deploy(tmp_path, version="2.0.0", app_cfg=None):
    root = tmp_path / "deploy"
    (root / "run.dist").mkdir(parents=True)
    (root / "run.dist" / "RELEASE.json").write_text(json.dumps({"product": "acme", "version": version, "framework_version": "1.32.0"}))
    (root / "config").mkdir()
    (root / "config" / "app.json").write_text(json.dumps(app_cfg or {"stations": ["st1", "st2"],
                                              "debug": {"enabled": True, "port": 8001, "broker_port": 1884, "token": "t"}}))
    return root


def test_explicit_state_dir_wins_and_reads_version_and_config(tmp_path):
    root = deploy(tmp_path)
    info = appinfo.discover(root, processes=lambda: [])
    assert info.found and info.kind == "installed" and info.app_version == "2.0.0" and info.framework_version == "1.32.0"
    assert info.stations() == ["st1", "st2"] and info.broker() == ("127.0.0.1", 1884) and info.in_app_recorder_enabled()
    assert info.db_path == root / "data" / "tmf.sqlite" and info.debug_dir == root / "data" / "debug"
    assert "explicit" in info.source


def test_a_running_app_process_is_found_without_any_hint(tmp_path, monkeypatch):
    monkeypatch.delenv("TMF_STATE_DIR", raising=False)
    root = deploy(tmp_path)
    procs = lambda: [{"pid": 7, "exe": str(root / "run.dist" / "run.exe"), "cmdline": "run.exe"},          # noqa: E731
                     {"pid": 8, "exe": r"C:\Other\run.exe", "cmdline": "x"}]
    info = appinfo.discover(None, processes=procs)
    assert info.found and info.state_root == root and "pid 7" in info.source


def test_a_deploy_root_next_to_the_tool_is_found(tmp_path, monkeypatch):
    monkeypatch.delenv("TMF_STATE_DIR", raising=False)
    root = deploy(tmp_path)
    tool = root / "tools" / "debug-tool"
    tool.mkdir(parents=True)
    info = appinfo.discover(None, tool_dir=tool, processes=lambda: [])
    assert info.found and info.state_root == root and "next to the tool" in info.source


def test_a_source_checkout_is_found(tmp_path, monkeypatch):
    monkeypatch.delenv("TMF_STATE_DIR", raising=False)
    (tmp_path / "backend" / "config").mkdir(parents=True)
    (tmp_path / "backend" / "core").mkdir()
    (tmp_path / "backend" / "core" / "__init__.py").write_text('__version__ = "1.31.1"\n')
    info = appinfo.discover(None, tool_dir=tmp_path / "debug_tool", processes=lambda: [])
    assert info.found and info.kind == "source" and info.state_root == tmp_path / "backend" and info.framework_version == "1.31.1"


def test_nothing_found_is_reported_not_guessed(tmp_path, monkeypatch):
    monkeypatch.delenv("TMF_STATE_DIR", raising=False)
    info = appinfo.discover(None, tool_dir=tmp_path / "x", processes=lambda: [])
    assert not info.found and info.db_path is None and "--state-dir" in info.notes[0]
    bad = appinfo.discover(tmp_path / "does-not-exist")
    assert not bad.found and "does not exist" in bad.source


def test_missing_config_degrades_to_defaults_with_a_note(tmp_path):
    root = tmp_path / "d"
    (root / "run.dist").mkdir(parents=True)
    info = appinfo.discover(root, processes=lambda: [])
    assert info.stations() == ["st1"] and info.broker() == ("127.0.0.1", 1883) and info.notes and not info.in_app_recorder_enabled()


def test_station_entries_may_be_objects(tmp_path):
    root = deploy(tmp_path, app_cfg={"stations": [{"id": "a"}, {"station": "b"}]})
    assert appinfo.discover(root, processes=lambda: []).stations() == ["a", "b"]


def test_core_url_follows_tmf_port(tmp_path, monkeypatch):
    monkeypatch.setenv("TMF_PORT", "18765")
    assert appinfo.discover(deploy(tmp_path), processes=lambda: []).core_url().endswith(":18765")

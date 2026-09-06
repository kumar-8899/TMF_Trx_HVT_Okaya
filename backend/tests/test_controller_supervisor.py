"""ControllerSupervisor config generation — the Instruments page is the single source
of instrument instances (PYTHON_CONTROLLER.md): a controller config_file `instruments`
list is ignored, and an unconfigured app yields a controller with NO instruments,
even in simulation."""

import json
import subprocess
import sys

import pytest

from core.services.controller_supervisor import ControllerSupervisor


class _Diag:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def info(self, *a, **k) -> None: pass

    def warning(self, _sub, msg, **k) -> None:
        self.warnings.append(msg)


def _sup(tmp_path, *, config_file=None, instruments=None) -> tuple[ControllerSupervisor, _Diag]:
    diag = _Diag()
    sup = ControllerSupervisor(
        stations=["st1"], broker_host="127.0.0.1", broker_port=1883,
        diag=diag, data_dir=tmp_path / "data", repo_root=tmp_path,
        config_file=config_file, instruments=instruments)
    return sup, diag


def _app_cfg(tmp_path, instruments) -> str:
    p = tmp_path / "controller.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "instruments": instruments,
        "stations": [{"station": "st1", "variable_map": "maps/st1.json"}],
    }), encoding="utf-8")
    return str(p)


PAGE = [{"id": "psu", "library": "keysight_e36xx", "params": {}, "simulated": True,
         "stations": ["st1"]}]
FILE = [{"id": "rogue", "library": "hidden_lib", "simulated": True}]


def test_unconfigured_app_gets_no_instruments(tmp_path):
    """No Instruments-page records -> the controller config has instruments: [] —
    the file's own list must NOT leak through (sim included)."""
    sup, diag = _sup(tmp_path, config_file=_app_cfg(tmp_path, FILE), instruments=None)
    cfg = json.loads(sup._write_config().read_text(encoding="utf-8"))
    assert cfg["instruments"] == []
    assert any("ignored" in w for w in diag.warnings)
    assert any("no instruments configured" in w for w in diag.warnings)


def test_page_instruments_override_config_file(tmp_path):
    sup, diag = _sup(tmp_path, config_file=_app_cfg(tmp_path, FILE), instruments=PAGE)
    cfg = json.loads(sup._write_config().read_text(encoding="utf-8"))
    assert cfg["instruments"] == PAGE
    assert any("ignored" in w for w in diag.warnings)


def test_page_instruments_without_config_file(tmp_path):
    sup, diag = _sup(tmp_path, instruments=PAGE)
    cfg = json.loads(sup._write_config().read_text(encoding="utf-8"))
    assert cfg["instruments"] == PAGE
    assert cfg["stations"] == [{"station": "st1"}]     # app's stations fill in
    assert not diag.warnings


def test_global_simulation_always_off_under_supervision(tmp_path):
    """Sim vs hardware is per-instrument (Instruments page). The generated config's
    global `simulation` (force-all, §12.1) must be False even if the app's
    controller.json says true — so a page record with simulated:false runs REAL."""
    p = tmp_path / "controller.json"
    p.write_text(json.dumps({"schema_version": 1, "simulation": True}), encoding="utf-8")
    sup, _ = _sup(tmp_path, config_file=str(p), instruments=PAGE)
    cfg = json.loads(sup._write_config().read_text(encoding="utf-8"))
    assert cfg["simulation"] is False


def test_variable_map_still_resolved_relative_to_config_file(tmp_path):
    sup, _ = _sup(tmp_path, config_file=_app_cfg(tmp_path, []), instruments=PAGE)
    cfg = json.loads(sup._write_config().read_text(encoding="utf-8"))
    vm = cfg["stations"][0]["variable_map"]
    assert vm.endswith("st1.json") and (tmp_path / "maps" / "st1.json").as_posix() in vm.replace("\\", "/")


# --- stop(): the controller child MUST be confirmed dead before a relaunch os._exit(42) ---
# An app-track backend spawns `run.exe --controller` as its OWN child; a hard exit that
# leaves it running orphans it — it keeps run.dist open (blocking every swap) and stays a
# second process driving instrument I/O.

def test_stop_confirms_child_is_dead_and_returns_true(tmp_path):
    sup, _ = _sup(tmp_path)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                            creationflags=flags)
    sup._proc = proc
    try:
        assert sup.stop() is True
        assert proc.poll() is not None          # actually terminated, not just signalled
        assert sup._proc is None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_stop_is_idempotent_when_there_is_no_child(tmp_path):
    sup, _ = _sup(tmp_path)
    assert sup.stop() is True                     # "nothing to stop" is success, not None
    assert sup.stop() is True


def test_start_suppresses_console_window_on_windows(tmp_path, monkeypatch):
    """Bug 2: the frozen `run.exe --controller` child is console-subsystem; spawned from the
    windowed launcher it would pop a fresh console window on every relaunch."""
    if sys.platform != "win32":
        pytest.skip("Windows-only creationflags")
    seen = {}

    def spy(*a, **k):
        seen["flags"] = k.get("creationflags", 0)
        raise RuntimeError("don't actually spawn in the test")

    monkeypatch.setattr(subprocess, "Popen", spy)
    sup, _ = _sup(tmp_path, instruments=PAGE)
    monkeypatch.setattr(sup, "_command", lambda: ([sys.executable, "-c", "pass"], tmp_path))
    sup.start()                                   # start() swallows the RuntimeError (logs a warning)
    assert seen["flags"] & subprocess.CREATE_NO_WINDOW
    assert seen["flags"] & subprocess.CREATE_NEW_PROCESS_GROUP

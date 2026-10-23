"""D7 — the vendored Mosquitto must not run from INSIDE run.dist.

`station.py` used to launch `run.dist/vendor/mosquitto/win64/mosquitto.exe` in place. A running exe
(and its DLLs) holds its directory open, so the launcher's `run.dist -> backup` rename failed with
WinError 5/32 on every in-app update while the broker was up. The broker is now staged to
`<deploy root>/data/broker/` and runs from there; and when a swap rename still fails the error
names the process holding the lock instead of a bare "Access is denied"."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def station(monkeypatch):
    spec = importlib.util.spec_from_file_location("station_under_test", REPO / "station.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vendor(root: Path) -> Path:
    d = root / "run.dist" / "vendor" / "mosquitto" / "win64"
    d.mkdir(parents=True)
    (d / "mosquitto.exe").write_bytes(b"EXE")
    (d / "mosquitto.conf").write_text("listener 1883 127.0.0.1\nallow_anonymous true\n")
    (d / "libcrypto-3-x64.dll").write_bytes(b"DLL")
    (d / "vcruntime140.dll").write_bytes(b"VC")
    return d / "mosquitto.exe"


def test_stage_broker_copies_exe_dlls_and_conf_outside_run_dist(station, tmp_path):
    exe = _vendor(tmp_path)
    staged = station.stage_broker(exe, tmp_path / "data" / "broker", swap_unit=tmp_path / "run.dist")
    assert staged == tmp_path / "data" / "broker" / "mosquitto.exe"
    for n in ("mosquitto.exe", "mosquitto.conf", "libcrypto-3-x64.dll", "vcruntime140.dll"):
        assert (staged.parent / n).is_file()
    assert (tmp_path / "run.dist" / "vendor" / "mosquitto" / "win64" / "mosquitto.exe").is_file()  # source intact


def test_stage_broker_leaves_a_broker_outside_the_swap_unit_alone(station, tmp_path):
    other = tmp_path / "tools" / "mosquitto.exe"
    other.parent.mkdir()
    other.write_bytes(b"EXE")
    assert station.stage_broker(other, tmp_path / "data" / "broker", swap_unit=tmp_path / "run.dist") == other
    assert not (tmp_path / "data").exists()


def test_stage_broker_refreshes_a_changed_exe_and_survives_a_locked_old_copy(station, tmp_path):
    exe = _vendor(tmp_path)
    dest = tmp_path / "data" / "broker"
    staged = station.stage_broker(exe, dest, swap_unit=tmp_path / "run.dist")
    exe.write_bytes(b"NEWER-EXE")                       # an update shipped a new broker
    staged = station.stage_broker(exe, dest, swap_unit=tmp_path / "run.dist")
    assert staged.read_bytes() == b"NEWER-EXE"

    exe.write_bytes(b"NEWEST")
    real = station.shutil.copy2

    def locked(src, dst, *a, **k):
        if str(dst).endswith("mosquitto.exe"):
            raise PermissionError(13, "in use")        # an orphaned broker still holds the staged exe
        return real(src, dst, *a, **k)
    station.shutil.copy2 = locked
    try:
        again = station.stage_broker(exe, dest, swap_unit=tmp_path / "run.dist")
    finally:
        station.shutil.copy2 = real
    assert again == staged and again.read_bytes() == b"NEWER-EXE"     # keeps running the existing copy


def test_start_broker_runs_the_staged_copy_not_the_one_in_run_dist(station, tmp_path, monkeypatch):
    exe = _vendor(tmp_path)
    monkeypatch.setattr(station, "ROOT", tmp_path)
    monkeypatch.setattr(station, "RUN_DIST", tmp_path / "run.dist")
    monkeypatch.setattr(station, "FROZEN", True)
    monkeypatch.setattr(station, "_port_open", lambda *a, **k: False)
    monkeypatch.setattr(station, "_mosquitto_exe", lambda: str(exe))
    spawned = {}

    class _P:
        pid = 1

    monkeypatch.setattr(station.subprocess, "Popen", lambda cmd, **k: spawned.setdefault("cmd", cmd) and _P())
    st = station.Station(type("A", (), {})())
    st.start_broker()
    cmd = spawned["cmd"]
    assert Path(cmd[0]) == tmp_path / "data" / "broker" / "mosquitto.exe"
    assert Path(cmd[cmd.index("-c") + 1]) == tmp_path / "data" / "broker" / "mosquitto.conf"
    assert "run.dist" not in str(cmd)


# --- the swap failure names the lock holder ----------------------------------------------------

def test_failed_swap_rename_names_the_process_holding_the_lock(monkeypatch):
    sys.path.insert(0, str(REPO / "backend"))
    try:
        import launcher
    finally:
        sys.path.pop(0)

    class _Src:
        name = "run.dist"

        def rename(self, dst):
            raise PermissionError(13, "Access is denied")

        def __str__(self):
            return r"D:\deploy\run.dist"

    monkeypatch.setattr(launcher, "lock_holders", lambda p: ["pid 4242 mosquitto.exe"])
    with pytest.raises(OSError) as ei:
        launcher._rename_with_retry(_Src(), Path("bak"), attempts=2, base_delay=0)
    msg = str(ei.value)
    assert "Access is denied" in msg and "mosquitto.exe" in msg and "4242" in msg


def test_lock_holders_is_empty_off_windows_and_never_raises(monkeypatch):
    sys.path.insert(0, str(REPO / "backend"))
    try:
        import launcher
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(launcher.os, "name", "posix")
    assert launcher.lock_holders(Path("/nope")) == []

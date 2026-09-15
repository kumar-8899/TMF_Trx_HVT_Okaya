"""build_release.py's run_station.exe machinery — the parts testable WITHOUT a real (multi-minute)
Nuitka compile. The actual compile is exercised for real by release.yml on every app-track release;
these tests lock in the two bugs found running that pipeline against a live app fork:

  1. A static `_WEBVIEW_NOFOLLOW` exclusion list is fragile to Nuitka/pywebview version combos that
     disagree on whether `webview.platforms.win32` needs excluding (confirmed empirically on two real
     machines, in OPPOSITE directions) — replaced with adaptive retry driven by Nuitka's own FATAL
     line, so there is no static list left to go stale.
  2. `_verify_run_station_exe`'s /healthz probe must refuse to "pass" against a port a stray process
     already occupies — otherwise it can report a compiled-but-non-booting exe as verified (reproduced
     for real: an exe with no run.dist exited in <1s, an unrelated already-running station on :8000
     answered the probe instead, and the smoke test returned True)."""

import pytest

import build_release as br


# --- _nuitka_webview_conflict: parsing Nuitka's own FATAL line -------------

def test_parses_the_conflicting_submodule_name():
    msg = ("FATAL: pywebview: Conflict between user and plugin decision for module "
           "'webview.platforms.win32'.")
    assert br._nuitka_webview_conflict(msg) == "win32"


def test_parses_from_full_multiline_nuitka_output():
    output = (
        "Nuitka-Inclusion:WARNING: Not allowed to include module 'webview.platforms.android' ...\n"
        "FATAL: pywebview: Conflict between user and plugin decision for module "
        "'webview.platforms.win32'.\n"
        "Nuitka-Reports: Compilation crash report written to file 'nuitka-crash-report.xml'.\n"
    )
    assert br._nuitka_webview_conflict(output) == "win32"


def test_returns_none_for_unrelated_failure_output():
    assert br._nuitka_webview_conflict("FATAL: some unrelated Nuitka error\n") is None
    assert br._nuitka_webview_conflict("") is None


# --- _verify_run_station_exe: refuse to "pass" against a stray listener ---

class _FakeResp:
    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_verify_aborts_when_port_already_answers(monkeypatch, tmp_path):
    """The exact false-positive this test locks in: something already on :8000 must not be
    mistaken for OUR freshly-built exe — verified WITHOUT ever spawning a process."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp(200))

    def _boom(*a, **k):
        raise AssertionError("must not spawn run_station.exe when the port is already occupied")
    monkeypatch.setattr(br.subprocess, "Popen", _boom)

    assert br._verify_run_station_exe(tmp_path, timeout=1) is False


def test_verify_proceeds_to_spawn_when_port_is_free(monkeypatch, tmp_path):
    """Sanity check for the guard's OTHER branch: a free port (urlopen raises OSError, matching a
    real connection-refused) must NOT short-circuit — it should still attempt to spawn."""
    import urllib.request

    def _refused(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _refused)

    spawned = {}

    class _FakeProc:
        pid = 4242
        def poll(self):
            spawned["polled"] = True
            return 1   # exits immediately — we only care that we GOT HERE, not full boot behavior
        returncode = 1
        def wait(self, timeout=None): pass

    def _fake_popen(cmd, **kw):
        spawned["cmd"] = cmd
        return _FakeProc()
    monkeypatch.setattr(br.subprocess, "Popen", _fake_popen)

    result = br._verify_run_station_exe(tmp_path, timeout=1)
    assert result is False              # the fake process "exited early" — correctly not verified
    assert spawned.get("polled") is True  # but we DID get past the pre-flight guard and spawn it
    assert str(tmp_path / "run_station.exe") in spawned["cmd"]


def test_verify_launches_windowed_not_no_window(monkeypatch, tmp_path):
    """Issue 4: the smoke test must launch the exe WINDOWED (no args) so a build that boots the
    backend but can never open a window is caught — the old `--no-window` probe missed it."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError()))

    class _FakeProc:
        pid = 4242
        returncode = 1
        def poll(self): return 1     # exits immediately; we only inspect the launch args
        def wait(self, timeout=None): pass

    captured = {}
    def _fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeProc()
    monkeypatch.setattr(br.subprocess, "Popen", _fake_popen)

    br._verify_run_station_exe(tmp_path, timeout=1)
    assert "--no-window" not in captured["cmd"]   # windowed, not headless
    assert captured["cmd"] == [str(tmp_path / "run_station.exe")]


# --- _process_has_visible_window: ctypes window enumeration ----------------

def test_process_has_visible_window_false_for_unknown_image():
    """The window-enumeration plumbing must run without error and report no window for a process
    image that isn't running (regardless of platform)."""
    assert br._process_has_visible_window("no_such_process_zzz_9999.exe") is False


# --- copy_vendor_broker: vcruntime beside mosquitto.exe (Issue 5) ---------

def _fake_broker_tree(tmp_path, with_vcruntime=True):
    repo = tmp_path / "repo"
    dist = tmp_path / "dist"
    src = repo / "deploy" / "vendor" / "mosquitto" / "win64"
    src.mkdir(parents=True)
    (src / "mosquitto.exe").write_text("exe")
    (src / "pthreadVC3.dll").write_text("dll")
    dist.mkdir(parents=True)
    if with_vcruntime:
        (dist / "vcruntime140.dll").write_text("rt")
        (dist / "vcruntime140_1.dll").write_text("rt1")
    return repo, dist


def test_copy_vendor_broker_places_vcruntime_beside_mosquitto(monkeypatch, tmp_path):
    repo, dist = _fake_broker_tree(tmp_path, with_vcruntime=True)
    monkeypatch.setattr(br, "REPO", repo)
    monkeypatch.setattr(br, "DIST", dist)
    br.copy_vendor_broker()
    dest = dist / "vendor" / "mosquitto" / "win64"
    assert (dest / "mosquitto.exe").is_file()
    assert (dest / "vcruntime140.dll").is_file()      # the Issue-5 fix: broker's own dir
    assert (dest / "vcruntime140_1.dll").is_file()


def test_copy_vendor_broker_gate_fails_without_vcruntime(monkeypatch, tmp_path):
    repo, dist = _fake_broker_tree(tmp_path, with_vcruntime=False)
    monkeypatch.setattr(br, "REPO", repo)
    monkeypatch.setattr(br, "DIST", dist)
    with pytest.raises(SystemExit):                   # build-gate: never ship a broker that can't start
        br.copy_vendor_broker()

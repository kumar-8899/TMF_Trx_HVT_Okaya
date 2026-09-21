"""build_release.py's run_station.exe machinery — the parts testable WITHOUT a real (multi-minute)
Nuitka compile. The actual compile is exercised for real by release.yml on every app-track release;
these tests lock in the bugs found running that pipeline against live app forks:

  1. Nuitka's bundled `PywebViewPlugin` arbitrates every `webview.platforms.*` import with its OWN
     Windows allow-list — which is missing `win32` even though `winforms.py` (the only Windows GUI
     backend pywebview has) imports it as a required helper, not an optional platform variant.
     Disagreeing with the plugin about ANY platforms submodule, in EITHER direction, hard-fails the
     compile ("Conflict between user and plugin decision"). An earlier fix retried adaptively,
     agreeing to exclude `win32` from the FATAL line — the compile then succeeded, but `winforms.py`
     could never import `win32` at RUNTIME, so the exe booted its backend but could never open a
     window (reproduced for real on a live app fork). The fix instead disables the plugin entirely
     (`--disable-plugin=pywebview`) and excludes only a FIXED set of genuinely-irrelevant platforms —
     `win32` is deliberately left out so Nuitka's ordinary static import-following includes it, since
     nothing is left to veto it. No adaptive retry needed: `winforms.py`'s import graph doesn't vary
     by Nuitka/pywebview version the way the plugin's own allow-list apparently does.
  2. `_verify_run_station_exe`'s /healthz probe must refuse to "pass" against a port a stray process
     already occupies — otherwise it can report a compiled-but-non-booting exe as verified (reproduced
     for real: an exe with no run.dist exited in <1s, an unrelated already-running station on :8000
     answered the probe instead, and the smoke test returned True)."""

import pytest

import build_release as br


# --- _WEBVIEW_NOFOLLOW: win32 must stay includable ------------------------

def test_webview_nofollow_excludes_only_genuinely_irrelevant_platforms():
    """`win32` (winforms.py's own required helper) and `winforms`/`edgechromium` (the two backends
    pywebview actually uses on Windows) must NOT be in the exclude list — only platforms that are
    unconditionally irrelevant on a Windows build."""
    assert set(br._WEBVIEW_NOFOLLOW) == {"android", "cocoa", "gtk", "qt", "mshtml", "edgehtml", "cef"}
    assert "win32" not in br._WEBVIEW_NOFOLLOW
    assert "winforms" not in br._WEBVIEW_NOFOLLOW
    assert "edgechromium" not in br._WEBVIEW_NOFOLLOW


# --- build_run_station_exe: disable the plugin, no adaptive retry ---------

class _FakeCompileResult:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def _stub_station(monkeypatch, tmp_path):
    """A minimal REPO layout so build_run_station_exe gets past its pre-flight checks and reaches
    the Nuitka command it would run — win32-only code path, so force the platform for CI hosts
    that run this suite on a non-Windows box."""
    monkeypatch.setattr(br.sys, "platform", "win32")
    (tmp_path / "station.py").write_text("# stub")
    monkeypatch.setattr(br, "REPO", tmp_path)
    monkeypatch.setattr(br, "BACKEND", tmp_path / "backend")
    monkeypatch.setattr(br, "OUT", tmp_path / "release-build")


def test_build_cmd_disables_the_pywebview_plugin_and_omits_win32_from_nofollow(monkeypatch, tmp_path):
    _stub_station(monkeypatch, tmp_path)
    captured = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeCompileResult(returncode=1, stderr="boom")
    monkeypatch.setattr(br.subprocess, "run", _fake_run)

    assert br.build_run_station_exe(jobs=1) is False
    cmd = captured["cmd"]
    assert "--disable-plugin=pywebview" in cmd
    nofollow = next(a for a in cmd if a.startswith("--nofollow-import-to="))
    excluded = {m.removeprefix("webview.platforms.") for m in nofollow.split("=", 1)[1].split(",")}
    assert excluded == set(br._WEBVIEW_NOFOLLOW)
    assert "win32" not in excluded


def test_build_does_not_retry_on_a_webview_conflict_message(monkeypatch, tmp_path):
    """The adaptive retry is gone: even a Nuitka output that LOOKS like the old plugin-conflict
    FATAL must not trigger a second compile attempt — the plugin is disabled, so that failure mode
    can no longer occur, and there's nothing left in the code to react to the message."""
    _stub_station(monkeypatch, tmp_path)
    calls = []

    def _fake_run(cmd, **kw):
        calls.append(cmd)
        return _FakeCompileResult(
            returncode=1,
            stderr="FATAL: pywebview: Conflict between user and plugin decision for module "
                   "'webview.platforms.win32'.")
    monkeypatch.setattr(br.subprocess, "run", _fake_run)

    assert br.build_run_station_exe(jobs=1) is False
    assert len(calls) == 1


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


# --- copy_user_docs: developer content never ships in a built station ----------

def _fake_docs_repo(tmp_path):
    import json
    repo = tmp_path / "repo"
    docs = repo / "docs"
    (docs / "help" / "user").mkdir(parents=True)
    (docs / "help" / "dev" / "guide").mkdir(parents=True)
    (docs / "generated").mkdir()
    (docs / "contracts").mkdir()
    (docs / "assets" / "screens").mkdir(parents=True)
    (docs / "help" / "user" / "getting-started.md").write_text("# hi")
    (docs / "help" / "dev" / "guide" / "start.md").write_text("# dev")
    (docs / "PRINCIPLES.md").write_text("# principles")
    (docs / "contracts" / "CORE.md").write_text("# core")
    (docs / "generated" / "facts.json").write_text("{}")
    for name in ("shared.png", "user.png", "devonly.png"):
        (docs / "assets" / "screens" / name).write_bytes(b"png")
    (docs / "assets" / "manifest.json").write_text(json.dumps({"schema_version": 1, "images": [
        {"id": "shared", "file": "screens/shared.png", "audience": "both"},
        {"id": "user", "file": "screens/user.png", "audience": "user"},
        {"id": "devonly", "file": "screens/devonly.png", "audience": "dev"},
    ]}))
    return repo


def test_copy_user_docs_ships_only_the_user_allowlist(tmp_path):
    repo = _fake_docs_repo(tmp_path)
    dest = tmp_path / "run.dist" / "docs"
    br.copy_user_docs(repo, dest)
    shipped = sorted(str(p.relative_to(dest)).replace("\\", "/") for p in dest.rglob("*") if p.is_file())
    assert "help/user/getting-started.md" in shipped
    assert not [p for p in shipped if p.startswith("help/dev") or "PRINCIPLES" in p
                or p.startswith("contracts") or p.startswith("generated")]
    assert "assets/screens/shared.png" in shipped and "assets/screens/user.png" in shipped
    assert "assets/screens/devonly.png" not in shipped                # dev-only image never ships


def test_copy_user_docs_filters_the_manifest_too(tmp_path):
    import json
    repo = _fake_docs_repo(tmp_path)
    dest = tmp_path / "run.dist" / "docs"
    br.copy_user_docs(repo, dest)
    ids = [e["id"] for e in json.loads((dest / "assets" / "manifest.json").read_text())["images"]]
    assert ids == ["shared", "user"]                                  # no trace of the dev image

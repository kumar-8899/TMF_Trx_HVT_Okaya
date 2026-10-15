"""build_release.py's run_station.exe machinery — the parts testable WITHOUT a real (multi-minute)
PyInstaller build. The actual build is exercised for real by release.yml on every app-track release;
these tests lock in:

  1. pywebview's platform selection (webview/guilib.py) tries importing EVERY backend in turn inside
     a try/except ImportError — android, cocoa, gtk, qt, winforms — so ordinary static analysis finds
     all of them regardless of which OS actually needs which. On Windows only `winforms` (+ its own
     `win32.py` helper module, not pywin32) and `edgechromium` are ever reached; the rest are
     excluded explicitly via --exclude-module (win32/winforms/edgechromium must NOT be excluded).
  2. `_verify_run_station_exe`'s /healthz probe must refuse to "pass" against a port a stray process
     already occupies — otherwise it can report a built-but-non-booting exe as verified (reproduced
     for real: an exe with no run.dist exited in <1s, an unrelated already-running station on :8000
     answered the probe instead, and the smoke test returned True)."""

import importlib.util
import json

import pytest

import build_release as br


@pytest.fixture(autouse=True)
def _drivers_present(monkeypatch):
    """build_backend now requires the report-db drivers on the build PC; most tests here are about
    something else, so pretend they are installed (the dedicated tests below exercise the check)."""
    monkeypatch.setattr(br, "report_db_drivers", lambda: list(br.REPORT_DB_DRIVERS))


# --- _WEBVIEW_NOFOLLOW: win32 must stay includable ------------------------

def test_webview_nofollow_excludes_only_genuinely_irrelevant_platforms():
    """`win32` (winforms.py's own required helper) and `winforms`/`edgechromium` (the two backends
    pywebview actually uses on Windows) must NOT be in the exclude list — only platforms that are
    unconditionally irrelevant on a Windows build."""
    assert set(br._WEBVIEW_NOFOLLOW) == {"android", "cocoa", "gtk", "qt", "mshtml", "edgehtml", "cef"}
    assert "win32" not in br._WEBVIEW_NOFOLLOW
    assert "winforms" not in br._WEBVIEW_NOFOLLOW
    assert "edgechromium" not in br._WEBVIEW_NOFOLLOW


# --- build_run_station_exe: PyInstaller onefile, correct platform excludes ---------

class _FakeBuildResult:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def _stub_station(monkeypatch, tmp_path):
    """A minimal REPO layout so build_run_station_exe gets past its pre-flight checks and reaches
    the PyInstaller command it would run — win32-only code path, so force the platform for CI
    hosts that run this suite on a non-Windows box."""
    monkeypatch.setattr(br.sys, "platform", "win32")
    (tmp_path / "station.py").write_text("# stub")
    monkeypatch.setattr(br, "REPO", tmp_path)
    monkeypatch.setattr(br, "BACKEND", tmp_path / "backend")
    monkeypatch.setattr(br, "OUT", tmp_path / "release-build")


def test_build_cmd_excludes_irrelevant_webview_platforms_but_not_win32(monkeypatch, tmp_path):
    _stub_station(monkeypatch, tmp_path)
    captured = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeBuildResult(returncode=1, stderr="boom")
    monkeypatch.setattr(br.subprocess, "run", _fake_run)

    assert br.build_run_station_exe() is False
    cmd = captured["cmd"]
    assert "--onefile" in cmd
    excluded = {a.removeprefix("--exclude-module=webview.platforms.")
                for a in cmd if a.startswith("--exclude-module=webview.platforms.")}
    assert excluded == set(br._WEBVIEW_NOFOLLOW)
    assert "win32" not in excluded
    assert "winforms" not in excluded
    assert "edgechromium" not in excluded


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


# --- copy_app_payload: the app's own portal content ships (pages, images, bundled PDFs) ---------

def test_copy_app_payload_ships_the_apps_portal_folder_but_never_recipes(monkeypatch, tmp_path):
    repo, dist = tmp_path / "repo", tmp_path / "dist"
    app = repo / "app" / "acme"
    (app / "portal" / "img").mkdir(parents=True)
    (app / "portal" / "library").mkdir()
    (app / "recipes").mkdir()
    (app / "controller.json").write_text("{}")
    (app / "VERSION").write_text("1.0.0")
    (app / "portal" / "wiring.md").write_text("# Wiring")
    (app / "portal" / "img" / "w.png").write_bytes(b"png")
    (app / "portal" / "library" / "manual.pdf").write_bytes(b"%PDF-1.4")
    (app / "recipes" / "site.json").write_text("{}")             # site data — must NOT ship
    dist.mkdir()
    monkeypatch.setattr(br, "REPO", repo)
    monkeypatch.setattr(br, "DIST", dist)
    br.copy_app_payload("acme")
    out = dist / "app" / "acme"
    assert (out / "portal" / "wiring.md").is_file()
    assert (out / "portal" / "img" / "w.png").is_file()
    assert (out / "portal" / "library" / "manual.pdf").is_file()
    assert not (out / "recipes").exists()


# --- build_backend: PyInstaller command construction (app packages always bundled) ------------

def _fake_app_with_step_package(repo, product="acme"):
    """A minimal app: one step-type package (`acme_steps`) + instrument_libs, named in
    controller.json's step_type_packages/library_packages — the two dynamically-loaded package
    kinds build_backend() bundles by name via --collect-submodules."""
    app = repo / "app" / product
    app.mkdir(parents=True)
    (app / "controller.json").write_text(json.dumps({
        "schema_version": 1, "step_type_packages": ["acme_steps"],
        "library_packages": ["instrument_libs"],
    }))
    (app / "VERSION").write_text("1.0.0")
    steps_pkg = app / "acme_steps"
    steps_pkg.mkdir()
    (steps_pkg / "__init__.py").write_text("# acme step types")
    il = repo / "instrument_libs"
    il.mkdir()
    (il / "__init__.py").write_text("# drivers")
    return app, steps_pkg, il


def _stub_build_backend(monkeypatch, tmp_path, *, find_spec=None):
    """Common scaffolding for build_backend() tests: fake REPO/BACKEND/OUT/DIST, a stubbed
    `_run` that creates OUT/run (what a real PyInstaller invocation would produce) and captures
    the command, and a stubbed `importlib.util.find_spec` (default: nothing optional installed,
    so tests don't depend on what's actually installed on the machine running them)."""
    repo = tmp_path / "repo"
    backend = tmp_path / "backend"
    backend.mkdir()
    out = tmp_path / "release-build"
    monkeypatch.setattr(br, "REPO", repo)
    monkeypatch.setattr(br, "BACKEND", backend)
    monkeypatch.setattr(br, "OUT", out)
    monkeypatch.setattr(br, "DIST", out / "run.dist")
    monkeypatch.setattr(importlib.util, "find_spec", find_spec or (lambda name: None))
    captured = {}

    def _fake_run(cmd, cwd, env=None):
        captured["cmd"] = cmd
        (out / "run").mkdir(parents=True)
    monkeypatch.setattr(br, "_run", _fake_run)
    return repo, out, captured


def test_build_backend_bundles_app_packages_and_controller_always(monkeypatch, tmp_path):
    """No narrow/opt-in toggle: the app's own step-type/library packages plus `controller` are
    always bundled by name (PyInstaller --collect-submodules) — this is the fix for the pyvisa
    regression (narrow-compile-surface silently dropped instrument_libs from the graph)."""
    repo, _out, captured = _stub_build_backend(monkeypatch, tmp_path)
    _fake_app_with_step_package(repo)

    br.build_backend(track="app", product="acme")
    cmd = captured["cmd"]
    assert "--collect-submodules=controller" in cmd
    assert "--collect-submodules=acme_steps" in cmd
    assert "--collect-submodules=instrument_libs" in cmd


def test_build_backend_renames_pyinstaller_output_to_dist(monkeypatch, tmp_path):
    """PyInstaller's --name ties both the output folder and the exe stem together, producing
    OUT/run — build_backend must rename it to DIST (OUT/run.dist), the one constant every other
    function reads."""
    _repo, out, _captured = _stub_build_backend(monkeypatch, tmp_path)

    br.build_backend()
    assert br.DIST.is_dir()
    assert not (out / "run").exists()


def test_build_backend_adds_vcruntime_dlls_when_present(monkeypatch, tmp_path):
    """mosquitto.exe (copy_vendor_broker) and the frozen runtime need vcruntime140(.dll/_1.dll)
    beside run.exe — sourced explicitly from the build Python's own install rather than hoping
    PyInstaller's dependency walker finds them."""
    _repo, _out, captured = _stub_build_backend(monkeypatch, tmp_path)
    base_prefix = tmp_path / "pyroot"
    base_prefix.mkdir()
    (base_prefix / "vcruntime140.dll").write_text("rt")
    (base_prefix / "vcruntime140_1.dll").write_text("rt1")
    monkeypatch.setattr(br.sys, "base_prefix", str(base_prefix))

    br.build_backend()
    cmd = captured["cmd"]
    assert f"--add-binary={base_prefix / 'vcruntime140.dll'};." in cmd
    assert f"--add-binary={base_prefix / 'vcruntime140_1.dll'};." in cmd


def test_build_backend_pyvisa_defaults_bundled_only_when_installed(monkeypatch, tmp_path):
    """pyvisa's own backend discovery goes through importlib.metadata entry points — invisible
    to any import-graph follower — so it needs an explicit --copy-metadata/--collect-all pair,
    added only when the packages are actually installed."""
    repo, _out, captured = _stub_build_backend(
        monkeypatch, tmp_path,
        find_spec=lambda name: object() if name in ("pyvisa", "pyvisa_py") else None)
    _fake_app_with_step_package(repo)

    br.build_backend(track="app", product="acme")
    cmd = captured["cmd"]
    assert "--copy-metadata=pyvisa" in cmd
    assert "--collect-all=pyvisa_py" in cmd


def test_build_backend_pyvisa_defaults_skipped_when_absent(monkeypatch, tmp_path):
    repo, _out, captured = _stub_build_backend(monkeypatch, tmp_path)
    _fake_app_with_step_package(repo)

    br.build_backend(track="app", product="acme")
    cmd = captured["cmd"]
    assert not any(a.startswith("--copy-metadata=pyvisa") or a.startswith("--collect-all=pyvisa")
                    for a in cmd)


def test_build_backend_does_not_force_sqlalchemy_or_uvicorn_submodules(monkeypatch, tmp_path):
    """Both already ship their own PyInstaller hooks that fire automatically from normal
    import-following — sqlalchemy's hook deliberately excludes sqlalchemy.testing, which a
    forced --collect-submodules would override. Forcing both (plus --clean) measured ~14 extra
    minutes on a real build (944s -> 115s once removed) for no behavioral benefit."""
    _repo, _out, captured = _stub_build_backend(monkeypatch, tmp_path)

    br.build_backend()
    cmd = captured["cmd"]
    assert "--collect-submodules=sqlalchemy" not in cmd
    assert "--collect-submodules=uvicorn" not in cmd
    assert "--clean" not in cmd


# --- FRAMEWORK CR B1/B2/B4: frozen-build safety nets ----------------------------------------------

def test_backend_excludes_gui_toolkits_that_shadow_the_msvc_runtime():
    """matplotlib -> PyQt5 -> an old MSVCP140.dll crashed NI-DAQmx in the frozen exe only."""
    assert {"matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter"} <= set(br._BACKEND_EXCLUDED_MODULES)


def test_build_backend_passes_the_excludes_and_bundles_the_debug_sidecar(monkeypatch, tmp_path):
    _repo, _out, captured = _stub_build_backend(monkeypatch, tmp_path)
    br.build_backend()
    cmd = captured["cmd"]
    for mod in br._BACKEND_EXCLUDED_MODULES:
        assert f"--exclude-module={mod}" in cmd
    assert "--collect-submodules=debug_server" in cmd          # run.exe --debug-server (FRAMEWORK CR A2)
    assert "debug_server/ui/*.html" in br.DATA_PATTERNS


def test_driver_metadata_is_derived_from_what_the_drivers_import(tmp_path, monkeypatch):
    il = tmp_path / "instrument_libs"
    il.mkdir()
    (il / "__init__.py").write_text("")
    (il / "drv.py").write_text("import pytest\nimport json\nfrom os import path\n")   # pytest = a real dist
    monkeypatch.setattr(br, "REPO", tmp_path)
    pkgs = {p.lower() for p in br._driver_metadata_packages("x")}
    assert "pytest" in pkgs                      # derived from the driver's import, no list edit needed
    assert "json" not in pkgs                    # stdlib is not a distribution
    assert "tmf-instrumentlib" not in pkgs


def test_native_driver_metadata_always_listed():
    assert {"pyvisa", "nidaqmx", "nitypes"} <= set(br._NATIVE_DRIVER_METADATA)


def test_merge_entitlements_adds_app_modules_and_unions_variants():
    base = {"entitlements": {"modules": {"runs": True}, "variants": {"runs": ["default"]}, "features": {}}}
    out = br.merge_entitlements(base, {"modules": {"acme_maint": True},
                                       "variants": {"acme_maint": ["default"], "runs": ["alt"]}})
    assert out["entitlements"]["modules"] == {"runs": True, "acme_maint": True}
    assert out["entitlements"]["variants"]["runs"] == ["alt", "default"]
    assert base["entitlements"]["modules"] == {"runs": True}                      # input untouched


def test_unentitled_modules_flags_what_the_gate_would_skip():
    lic = {"entitlements": {"modules": {"runs": True, "daq": False}, "variants": {"runs": ["default"]}}}
    cfg = {"modules": [{"id": "runs", "variant": "default"}, {"id": "daq", "variant": "default"},
                       {"id": "acme_maint", "variant": "default"}, {"id": "runs", "variant": "other"}]}
    bad = br.unentitled_modules(cfg, lic)
    assert len(bad) == 3 and any("daq" in b for b in bad) and any("acme_maint" in b for b in bad)
    assert any("variant" in b for b in bad)


def test_shipped_framework_config_is_fully_entitled():
    """The framework's own example app config must activate every module under its example license."""
    root = br.BACKEND / "config"
    cfg = json.loads((root / "app.example.json").read_text(encoding="utf-8"))
    lic = json.loads((root / "license.example.json").read_text(encoding="utf-8"))
    assert br.unentitled_modules(cfg, lic) == []


def test_ship_license_fails_the_build_for_an_unentitled_app_module(tmp_path, monkeypatch):
    (tmp_path / "app" / "acme").mkdir(parents=True)
    monkeypatch.setattr(br, "REPO", tmp_path)
    monkeypatch.setattr(br, "DIST", tmp_path / "dist")
    cfg = {"modules": [{"id": "acme_maint", "variant": "default"}]}
    with pytest.raises(SystemExit) as ei:
        br.ship_license("acme", cfg)
    assert "acme_maint" in str(ei.value) and "license.entitlements.json" in str(ei.value)
    (tmp_path / "app" / "acme" / "license.entitlements.json").write_text(
        json.dumps({"modules": {"acme_maint": True}}))
    br.ship_license("acme", cfg)                                                  # now entitled -> ships
    shipped = json.loads((tmp_path / "dist" / "config" / "license.example.json").read_text())
    assert shipped["entitlements"]["modules"]["acme_maint"] is True


def test_release_probes_example_matches_its_schema():
    from jsonschema import Draft202012Validator
    root = br.REPO
    schema = json.loads((root / "deploy" / "release-probes.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "docs" / "templates" / "release-probes.example.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(example)


# --- D13: step-type schemas must ride in the frozen build -------------------------------------

def test_copy_step_type_schemas_ships_core_and_app_schemas(monkeypatch, tmp_path):
    """`--collect-submodules` bundles .py only; a step type resolves `schemas/<id>.json` / its
    `schema.json` beside the handler, so without these copies the frozen catalog has schema=None
    and recipe validation silently skips (field defect D13)."""
    repo, dist = tmp_path / "repo", tmp_path / "dist"
    core = repo / "controller" / "controller" / "step_types" / "schemas"
    core.mkdir(parents=True)
    (core / "wait.json").write_text("{}")
    app = repo / "app" / "acme"
    (app / "acme_steps" / "hipot").mkdir(parents=True)
    (app / "acme_steps" / "hipot" / "schema.json").write_text("{}")
    (app / "acme_steps" / "hipot" / "handler.py").write_text("# code")
    (app / "controller.json").write_text(json.dumps({"step_type_packages": ["acme_steps"]}))
    dist.mkdir()
    monkeypatch.setattr(br, "REPO", repo)
    monkeypatch.setattr(br, "DIST", dist)
    n = br.copy_step_type_schemas("acme")
    assert (dist / "controller" / "step_types" / "schemas" / "wait.json").is_file()
    assert (dist / "acme_steps" / "hipot" / "schema.json").is_file()
    assert not (dist / "acme_steps" / "hipot" / "handler.py").exists()     # code is in the exe
    assert not (dist / "acme_steps" / "controller.json").exists()
    assert n == 2


def test_copy_step_type_schemas_fails_loudly_when_core_schemas_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(br, "REPO", tmp_path)
    monkeypatch.setattr(br, "DIST", tmp_path / "dist")
    with pytest.raises(SystemExit, match="step-type schemas"):
        br.copy_step_type_schemas("acme")


# --- D10: stale frontend must not ship --------------------------------------------------------

def _fe(tmp_path):
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "a.tsx").write_text("one")
    (fe / "package.json").write_text("{}")
    (fe / "dist").mkdir()
    (fe / "dist" / "index.html").write_text("STALE")
    return fe


def test_frontend_src_hash_tracks_sources_and_ignores_dist(monkeypatch, tmp_path):
    fe = _fe(tmp_path)
    monkeypatch.setattr(br, "REPO", tmp_path)
    h1 = br.frontend_src_hash()
    (fe / "dist" / "index.html").write_text("rebuilt")
    assert br.frontend_src_hash() == h1                                     # dist output is not input
    (fe / "src" / "a.tsx").write_text("two")
    assert br.frontend_src_hash() != h1
    h2 = br.frontend_src_hash()
    (fe / "src" / "overrides").mkdir()
    (fe / "src" / "overrides" / "Runs.tsx").write_text("fork screen")        # a fork override counts
    assert br.frontend_src_hash() != h2


def test_build_always_rebuilds_even_when_dist_exists_and_stamps_it(monkeypatch, tmp_path):
    fe = _fe(tmp_path)
    dist = tmp_path / "out" / "run.dist"
    dist.mkdir(parents=True)
    ran = []

    def fake_run(cmd, cwd, env=None):
        ran.append(cmd)
        (fe / "dist" / "index.html").write_text("FRESH")

    monkeypatch.setattr(br, "REPO", tmp_path)
    monkeypatch.setattr(br, "DIST", dist)
    monkeypatch.setattr(br, "_run", fake_run)
    monkeypatch.setattr(br, "_git_sha", lambda: "abc1234")
    monkeypatch.setattr(br, "copy_user_docs", lambda *a, **k: None)
    monkeypatch.setattr(br, "OUT", tmp_path / "out")
    monkeypatch.setattr(br, "BACKEND", tmp_path / "backend")
    br.copy_docs_frontend_dll(skip_frontend=False, ui_version="2.3.4")
    assert ran and ran[0][:3] == ["npm", "run", "build"]                    # stale dist was NOT trusted
    assert (dist / "frontend" / "index.html").read_text() == "FRESH"
    stamp = json.loads((dist / "frontend" / "build-info.json").read_text())
    assert stamp["app_version"] == "2.3.4" and stamp["git_sha"] == "abc1234"
    assert stamp["src_hash"] == br.frontend_src_hash()


def test_verify_stamp_helper_catches_a_stale_bundle(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, str(br.REPO / "deploy"))
    try:
        import verify_frontend_stamp as v
    finally:
        sys.path.pop(0)
    fe = _fe(tmp_path)
    monkeypatch.setattr(br, "REPO", tmp_path)
    (tmp_path / "app" / "acme").mkdir(parents=True)
    (tmp_path / "app" / "acme" / "VERSION").write_text("2.3.4")
    dist = tmp_path / "run.dist"
    (dist / "frontend").mkdir(parents=True)
    good = {"app_version": "2.3.4", "git_sha": "abc1234", "src_hash": br.frontend_src_hash()}
    (dist / "frontend" / "build-info.json").write_text(json.dumps(good))
    assert v.check(dist, "acme", repo=tmp_path, sha="abc1234") == []
    (fe / "src" / "a.tsx").write_text("edited after the build")              # source moved on
    errs = v.check(dist, "acme", repo=tmp_path, sha="abc1234")
    assert any("stale" in e for e in errs)
    errs = v.check(dist, "acme", repo=tmp_path, sha="deadbee")
    assert any("git" in e for e in errs)
    (dist / "frontend" / "build-info.json").unlink()
    assert any("build-info.json" in e for e in v.check(dist, "acme", repo=tmp_path, sha="abc1234"))


# --- D8: optional Authenticode signing, BEFORE the manifest hashes the files --------------------

def test_sign_release_binaries_signs_what_exists_and_is_skipped_off_windows(monkeypatch, tmp_path):
    repo, out = tmp_path / "repo", tmp_path / "out"
    dist = out / "run.dist"
    (repo / "deploy").mkdir(parents=True)
    (repo / "deploy" / "sign-binaries.ps1").write_text("# stub")
    (dist / "vendor" / "mosquitto" / "win64").mkdir(parents=True)
    (dist / "run.exe").write_bytes(b"x")
    (dist / "vendor" / "mosquitto" / "win64" / "mosquitto.exe").write_bytes(b"x")
    # run_station.exe deliberately absent (fail-soft build) -> must be skipped, not an error
    for name, val in (("REPO", repo), ("OUT", out), ("DIST", dist)):
        monkeypatch.setattr(br, name, val)
    calls = []
    monkeypatch.setattr(br.subprocess, "run",
                        lambda cmd, **k: calls.append(cmd) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(br.sys, "platform", "win32")
    files = br.sign_release_binaries()
    assert [p.name for p in files] == ["run.exe", "mosquitto.exe"]
    paths = calls[0][calls[0].index("-Paths") + 1]
    assert "run.exe" in paths and "mosquitto.exe" in paths and "run_station.exe" not in paths
    monkeypatch.setattr(br.sys, "platform", "linux")
    assert br.sign_release_binaries() == [] and len(calls) == 1


def test_a_configured_signature_that_fails_fails_the_build(monkeypatch, tmp_path):
    repo, out = tmp_path / "repo", tmp_path / "out"
    (repo / "deploy").mkdir(parents=True)
    (repo / "deploy" / "sign-binaries.ps1").write_text("# stub")
    (out / "run.dist").mkdir(parents=True)
    (out / "run.dist" / "run.exe").write_bytes(b"x")
    for name, val in (("REPO", repo), ("OUT", out), ("DIST", out / "run.dist")):
        monkeypatch.setattr(br, name, val)
    monkeypatch.setattr(br.sys, "platform", "win32")
    monkeypatch.setattr(br.subprocess, "run", lambda cmd, **k: type("R", (), {"returncode": 1})())
    with pytest.raises(SystemExit, match="code signing failed"):
        br.sign_release_binaries()


def test_main_signs_before_the_manifest_hashes_the_tree():
    src = (br.BACKEND / "build_release.py").read_text(encoding="utf-8")
    body = src[src.index("def main()"):]
    assert body.index("sign_release_binaries()") < body.index("RELEASE.json must ride")   # manifest() sits between


# --- report/MES database drivers must be in the frozen exe (Okaya C8) -----------------------------

def test_report_db_drivers_fails_the_build_when_one_is_missing(monkeypatch):
    import importlib.util as iu
    real = iu.find_spec
    monkeypatch.undo()                      # drop the autouse stub: test the real function
    monkeypatch.setattr(iu, "find_spec", lambda n, *a, **k: None if n == "pyodbc" else real(n, *a, **k))
    with pytest.raises(SystemExit) as ei:
        br.report_db_drivers()
    msg = str(ei.value)
    assert "pyodbc" in msg and "report-db" in msg and "BUILD FAILED" in msg


def test_report_db_drivers_returns_both_when_installed(monkeypatch):
    import importlib.util as iu
    monkeypatch.undo()
    monkeypatch.setattr(iu, "find_spec", lambda n, *a, **k: object())
    assert br.report_db_drivers() == ["pymysql", "pyodbc"]


def test_build_backend_forces_both_db_drivers_in_as_hidden_imports(monkeypatch, tmp_path):
    """SQLAlchemy imports mssql's pyodbc dynamically - invisible to PyInstaller - so it must be named."""
    seen = {}
    monkeypatch.setattr(br, "OUT", tmp_path / "out")
    monkeypatch.setattr(br, "DIST", tmp_path / "out" / "run.dist")
    monkeypatch.setattr(br, "BACKEND", tmp_path / "backend")
    (tmp_path / "backend").mkdir()

    def fake_run(cmd, cwd, env=None):
        seen["cmd"] = cmd
        (tmp_path / "out" / "run").mkdir(parents=True)
    monkeypatch.setattr(br, "_run", fake_run)
    br.build_backend("framework")
    assert "--hidden-import=pyodbc" in seen["cmd"] and "--hidden-import=pymysql" in seen["cmd"]


def test_gate_runs_the_driver_check_inside_the_built_exe():
    """run.exe --check-db-drivers is the entry the release gate calls; verify-build.ps1 must call it."""
    run_py = (br.BACKEND / "run.py").read_text(encoding="utf-8")
    gate = (br.REPO / "deploy" / "verify-build.ps1").read_text(encoding="utf-8")
    assert "--check-db-drivers" in run_py and "--check-db-drivers" in gate

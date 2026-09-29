"""Release build — PyInstaller-frozen backend.

Freezes the Python backend into a standalone `run.dist/run.exe` (no system Python/pip
needed on the client). No IP protection — PyInstaller ships plain bytecode, trivially
decompilable, same as `tmf-sidecar.spec` (now retired) always was. That's a deliberate,
explicit tradeoff for build time: freezing has no compile step, so a full app-track
build is minutes, not the 15-45 min a real C compile (Nuitka, the prior approach) cost.
Re-introduce IP protection later as its own decision if it's ever needed again — see
docs/decisions/0003-pyinstaller-and-bundle-packages.md.

Output layout (SECURE_DISTRIBUTION.md §5):

    release-build/
      run.dist/            frozen backend (run.exe + native libs) = the swap unit + the .zip
        launcher.py        update supervisor (catches exit-42, applies the staged run.dist)
        modules/**         manifest.json / schemas / step_types / known_issues (data)
        core/schemas/*     app/license schema JSON (data)
        config/*.example.json
        frontend/          built SPA (served single-origin; resolve_frontend_dist prefers this)
        docs/              in-app USER manual only: help/user + referenced shared images
                           (help.catalog resolves this first; developer docs are NEVER shipped)
        --- app track (--track app): run.exe ALSO runs the controller (run.exe --controller),
            and these bundle INSIDE run.dist so a swap carries it all: ---
        app/<product>/     app DEFINITION: controller.json, maps/, specs/ (NO recipes/creds)
        instrument_libs/   copied drivers (provenance; imports use the bundled copy)
        vendor/mosquitto/  vendored broker (win64: mosquitto.exe + DLLs + loopback conf) — the
                           frozen station starts its OWN broker: no Mosquitto install/service/admin
      run_station.exe      frozen windowed launcher (deploy root, BESIDE run.dist) — the ONE
                           `station.py` entrypoint Nuitka-compiled, bundling pywebview + the
                           launcher module: client needs NO Python/pip. Its own release asset;
                           survives the run.dist swap because it's a sibling. FAIL-SOFT
                           (build_run_station_exe): a compile or runtime-smoke-test failure WARNS
                           + returns rather than aborting — run.dist below still gets built either
                           way, since only the offline setup.exe needs this exe.
      keystation_core.dll  native licensing core (app.json licensing.core_lib)
      RELEASE.json         version + SHA-256 manifest of the above
    Everything the running app SERVES (UI, help, app def, drivers) is inside run.dist, so the
    published <slug>-<ver>.zip is a complete app AND an in-app update refreshes all of it.

Usage:  python build_release.py [--track framework|app] [--product <name>]
                                 [--app-config <path>] [--skip-frontend]
App track freezes ONE exe: run.exe also runs the controller (`run.exe --controller`), with the
app's step-type packages + library packages + instrument_libs bundled in by NAME (PyInstaller
`--collect-submodules`, resolved from `app/<product>/controller.json` — the same mechanism used
for `core`/`modules`, since dynamic discovery is invisible to static analysis either way), so a
frozen app runs its OWN test sequence, not just the shell. There is only one mode — everything
app-owned is always bundled; no narrow/compiled-in toggle (that distinction only ever meant
something under a real machine-code compiler, which PyInstaller isn't).
Two framework-owned defaults are bundled automatically when installed, because their real
dependency (a driver's `import pyvisa`) is normally caught by ordinary import-following once
`instrument_libs` is in the graph, but PYVISA'S OWN backend discovery goes through
`importlib.metadata` entry points — invisible to ANY import-graph follower: `pyvisa`
(`--copy-metadata`, so its entry-point lookup succeeds) and `pyvisa_py` (`--collect-all`, since
nothing statically imports it). Silently skipped if not installed — see
docs/decisions/0003-pyinstaller-and-bundle-packages.md.
The signed Keystation framework-release registration (manifest + build_timestamp)
happens in CI / on the issuer, not here — this script only produces + hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent
OUT = REPO / "release-build"
DIST = OUT / "run.dist"

# Data files read at runtime via package-relative paths (mirrors tmf-sidecar.spec).
DATA_PATTERNS = (
    "modules/**/manifest.json",
    "modules/**/schemas/*.json",
    "modules/**/step_types/**/*.json",
    "modules/**/known_issues/*.json",
    "core/schemas/*.json",
    "config/*.example.json",
)


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


def _app_build_env(product: str) -> dict:
    """PyInstaller resolves `--collect-submodules` against sys.path, so put the app's package
    roots on PYTHONPATH: the repo root (for `instrument_libs`), `app/<product>` (for
    `<name>_steps`), and `controller/` (the `controller` package the recipe catalog imports)."""
    import os
    roots = os.pathsep.join([str(REPO), str(REPO / "app" / product), str(REPO / "controller")])
    env = dict(os.environ)
    env["PYTHONPATH"] = roots + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _app_include_packages(product: str) -> list[str]:
    """The app's dynamically-named packages — read from `app/<product>/controller.json`
    (`step_type_packages` + `library_packages`) plus the repo-root `instrument_libs/` (copied
    drivers). They load by NAME at runtime (import_module), invisible to static analysis, so each
    is force-bundled (`--collect-submodules`) exactly like `core`/`modules` are — there is only
    one mode, always bundled; see docs/decisions/0003-pyinstaller-and-bundle-packages.md."""
    pkgs: list[str] = []
    if (REPO / "instrument_libs" / "__init__.py").is_file():
        pkgs.append("instrument_libs")
    ctrl = REPO / "app" / product / "controller.json"
    if ctrl.is_file():
        try:
            data = json.loads(ctrl.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        for key in ("step_type_packages", "library_packages"):
            for pkg in (data.get(key) or []):
                if pkg not in pkgs:
                    pkgs.append(pkg)
    return pkgs


# Third-party packages a driver's `import pyvisa` normally pulls in for free once
# `instrument_libs` is in the bundle (ordinary import-graph following) — EXCEPT pyvisa's own
# backend discovery, which goes through `importlib.metadata` entry points and is invisible to
# ANY static import-follower, PyInstaller or otherwise. Bundled only when installed (mirrors the
# `keystation` opt-in check below) — never a hard requirement, never a config surface; add here
# only if another package turns out to need the same entry-point treatment.
_PYVISA_METADATA_PACKAGES = ("pyvisa",)      # --copy-metadata: fixes entry_points() lookup
_PYVISA_BACKEND_PACKAGES = ("pyvisa_py",)    # --collect-all: nothing statically imports it


def build_backend(track: str = "framework", product: str = "super_test_app") -> None:
    """Freeze the backend with PyInstaller (onedir, flat layout) into DIST = OUT/"run.dist".
    PyInstaller ties --name to both the output folder AND the exe stem, so this always produces
    OUT/run/run.exe first, then does one explicit rename to DIST — the like-for-like replacement
    of what Nuitka's automatic `.dist`-suffixed --output-dir already did; nothing downstream
    needs to know PyInstaller was involved, DIST is still the one constant everything else reads.
    """
    import importlib.util
    workpath = OUT / "build"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(BACKEND / "run.py"),
        "--onedir",
        "--contents-directory=.",     # flat layout: run.exe + everything sit as siblings, no
                                       # _internal/ subfolder — matches every sys.executable-parent
                                       # path resolution in core/services/{spa,docs_paths,config}.py
        "--name=run",
        f"--distpath={OUT}",
        f"--workpath={workpath}",
        f"--specpath={workpath}",
        "--noconfirm",
        "--console",
        # dynamic discovery (core.framework.registry.discover) is invisible to
        # static analysis - force-bundle the whole tree:
        "--collect-submodules=core",
        "--collect-submodules=modules",
        # C-extension / runtime deps that static analysis can miss:
        "--collect-all=argon2",
        "--collect-submodules=aiosqlite",
        "--collect-submodules=pypdf",   # portal library text extraction (optional import)
        # uvicorn and sqlalchemy are deliberately NOT forced here: both already ship their own
        # PyInstaller hooks (hook-uvicorn.py, hook-sqlalchemy.py) that fire automatically once
        # they're reached via normal import-following. sqlalchemy's own hook is actually SMARTER
        # than a blanket --collect-submodules — it explicitly excludes sqlalchemy.testing, which
        # a forced flag would override. Forcing both here was measured to add ~14 minutes to the
        # build (944s -> 115s once removed) for no behavioral benefit.
    ]
    # keystation SDK is optional + deployment-specific (external repo, ships with the
    # SDK+DLL). Bundle it only when installed; the provider lazy-imports it otherwise.
    for opt in ("keystation",):
        if importlib.util.find_spec(opt) is not None:
            cmd.append(f"--collect-all={opt}")
        else:
            print(f"note: '{opt}' not installed - not bundled (added at deployment)")
    # vcruntime140(.dll/_1.dll): mosquitto.exe (copy_vendor_broker) and the broader frozen
    # runtime need these beside run.exe. PyInstaller's own dependency walker usually finds them,
    # but don't wait to find out — source them explicitly from the build Python's own install.
    for name in ("vcruntime140.dll", "vcruntime140_1.dll"):
        src_dll = Path(sys.base_prefix) / name
        if src_dll.is_file():
            cmd.append(f"--add-binary={src_dll};.")
    env = None
    if track == "app":
        # (modules/recipe/catalog.py), so the CONTROLLER package must be bundled too. The app's
        # OWN step-type/library packages + instrument_libs are ALWAYS bundled by name — there is
        # no narrow/compiled-in toggle; that distinction only ever meant something under a real
        # machine-code compiler (Nuitka), which PyInstaller isn't.
        cmd.append("--collect-submodules=controller")
        for pkg in _app_include_packages(product):
            cmd.append(f"--collect-submodules={pkg}")
        for pkg in _PYVISA_METADATA_PACKAGES:
            if importlib.util.find_spec(pkg) is not None:
                cmd.append(f"--copy-metadata={pkg}")
        for pkg in _PYVISA_BACKEND_PACKAGES:
            if importlib.util.find_spec(pkg) is not None:
                cmd.append(f"--collect-all={pkg}")
        env = _app_build_env(product)
    _run(cmd, cwd=BACKEND, env=env)
    produced = OUT / "run"
    if not produced.is_dir():
        raise SystemExit(f"PyInstaller reported success but {produced} was not produced")
    if DIST.exists():
        shutil.rmtree(DIST)
    produced.rename(DIST)


def _verify_frozen_controller(product: str) -> None:
    """GATE: the frozen backend exe MUST also run as the controller (`run.exe --controller`) — load
    the app's step packages, pass the conformance re-check, build the registry, and reach
    `instruments:` with no crash. Catches frozen-only failures (stdlib not bundled →
    `Failed to import encodings`; `inspect.getsource` in the conformance gate → `could not get
    source`). Launch with a real config + an unreachable broker so it can't hang, and FAIL the whole
    build if the controller can't start — a frozen app that boots the UI but can't run the controller
    is a FAIL. Runs for --track app right after the backend compile (fail fast, one exe)."""
    import tempfile
    exe = DIST / ("run.exe" if sys.platform == "win32" else "run")
    steps = [p for p in _app_include_packages(product) if p != "instrument_libs"]
    # No step_type_paths/library_paths needed: every package here is bundled into run.exe by
    # name (build_backend's --collect-submodules), so plain import_module(pkg) finds it —
    # no sys.path injection required.
    cfg = {"schema_version": 1, "broker": {"host": "127.0.0.1", "port": 9},   # port 9 = discard
           "step_type_packages": steps,
           "library_packages": [p for p in _app_include_packages(product) if p == "instrument_libs"],
           "stations": [{"station": "st1"}], "simulation": False}
    tmpdir = Path(tempfile.mkdtemp())
    (tmpdir / "verify.json").write_text(json.dumps(cfg), encoding="utf-8")
    combined = ""
    try:
        r = subprocess.run([str(exe), "--controller", str(tmpdir / "verify.json")],
                           capture_output=True, text=True, timeout=40)
        combined = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as exc:      # broker retry keeps it alive — output is enough
        combined = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    reached = "instruments:" in combined or "controller up" in combined
    head = combined.split("instruments:", 1)[0]   # a startup crash lands BEFORE `instruments:`
    crash = any(m in head for m in (
        "Failed to import encodings", "No module named", "Fatal Python error", "Traceback",
        "could not get source"))
    ok = reached and not crash
    print(f"controller verify (run.exe --controller): startup {'OK' if ok else 'FAILED'}")
    if not ok:
        raise SystemExit(
            "BUILD FAILED: `run.exe --controller` cannot complete startup "
            f"(crash={crash}, reached_startup={reached}).\n"
            f"  output tail: {combined[-700:]!r}\n"
            "  A frozen app that boots the UI but can't run the controller is a FAIL — check that "
            "every step-type/library package + instrument_libs is actually being bundled "
            "(_app_include_packages / --collect-submodules) and that PYTHONPATH resolves them at "
            "build time (_app_build_env).")


def copy_data() -> None:
    n = 0
    for pattern in DATA_PATTERNS:
        for src in BACKEND.glob(pattern):
            dest = DIST / src.relative_to(BACKEND)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            n += 1
    print(f"data files: {n}")
    # The update supervisor ships INSIDE the swap unit (run.dist): the launcher catches the
    # backend's exit-42 and applies the staged run.dist. Hashed by manifest() + zipped by
    # package_artifact(), so every swapped-in build carries its own launcher (UPDATES.md §1).
    shutil.copy2(BACKEND / "launcher.py", DIST / "launcher.py")
    print("launcher: launcher.py -> run.dist/launcher.py")


def copy_user_docs(repo: Path, dest: Path) -> None:
    """Ship ONLY the customer-facing docs into a built station — an ALLOWLIST, not "copy docs/ minus
    a few dirs", so a developer doc added tomorrow can never leak by default:

      docs/help/user/**          the user manual
      docs/assets/manifest.json  filtered to audience user|both
      docs/assets/<image>        only images that filtered manifest references

    Everything else (docs/help/dev, PRINCIPLES/ARCHITECTURE/contracts, docs/generated, dev-only
    screenshots) stays in the source repo. help.catalog.is_frozen() hides dev pages at runtime too."""
    import json
    docs = repo / "docs"
    user_src = docs / "help" / "user"
    if user_src.is_dir():
        shutil.copytree(user_src, dest / "help" / "user", dirs_exist_ok=True)
    n_img = 0
    manifest = docs / "assets" / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        kept = [e for e in data.get("images", []) if e.get("audience", "both") != "dev"]
        for e in kept:
            src = docs / "assets" / e["file"]
            if src.is_file():
                out = dest / "assets" / e["file"]
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
                n_img += 1
        (dest / "assets").mkdir(parents=True, exist_ok=True)
        (dest / "assets" / "manifest.json").write_text(
            json.dumps({**data, "images": kept}, indent=2), encoding="utf-8")
    print(f"docs: user manual + {n_img} shared image(s) -> run.dist/docs (developer docs NOT shipped)")


def copy_docs_frontend_dll(skip_frontend: bool) -> None:
    # The SPA + in-app help ride INSIDE run.dist (the swap unit), so the published .zip is a
    # COMPLETE app (a client install has the UI) AND an in-app update refreshes the UI/help too —
    # a swap replaces run.dist wholesale. The fork's OWN `frontend/dist` (built here) already
    # contains its custom screen overrides (frontend/src/app/overrides/*), so they ship automatically.
    # spa.py / help.catalog resolve run.dist/{frontend,docs} first (v1.12.0). Docs are the USER
    # allowlist only — developer content never ships (copy_user_docs).
    copy_user_docs(REPO, DIST / "docs")
    if not skip_frontend:
        fe = REPO / "frontend" / "dist"
        if not fe.exists():
            _run(["npm", "run", "build"], cwd=REPO / "frontend")   # builds the fork's UI incl. overrides
        shutil.copytree(fe, DIST / "frontend", dirs_exist_ok=True)
    # Windowed launcher SOURCE — the one `station.py` entrypoint, shipped to the deploy root (NOT
    # the swap unit; it launches run.dist) as the scripted fallback: `python station.py` beside
    # run.dist works even without the compiled run_station.exe (station.py detects the run.dist
    # layout and supervises it in-process).
    win_entry = REPO / "station.py"
    if win_entry.is_file():
        shutil.copy2(win_entry, OUT / "station.py")
        print("windowed entry: station.py -> deploy root")
    for candidate in (
        BACKEND / "keystation_core.dll",
        Path("D:/Experiment/Build License Track/core/target/release/keystation_core.dll"),
    ):
        if candidate.exists():
            shutil.copy2(candidate, OUT / "keystation_core.dll")
            print("keystation core:", candidate)
            break
    else:
        print("WARNING: keystation_core.dll not found - ship it separately")


def copy_vendor_broker() -> None:
    """Vendor Mosquitto INTO run.dist so the frozen station carries its own broker — no
    Mosquitto installer, no Windows service, no admin (DEPLOY_STATION.md). `run_station`'s
    `_mosquitto_exe()` already prefers `RUN_DIST/vendor/mosquitto/win64/mosquitto.exe`, and
    because it rides inside run.dist every app-track build (and every in-app update) carries
    it, so it survives swaps. Source: `deploy/vendor/mosquitto/win64/` (mosquitto.exe + DLLs +
    a loopback mosquitto.conf), populated by `deploy/fetch-mosquitto.ps1` before the build."""
    src = REPO / "deploy" / "vendor" / "mosquitto" / "win64"
    if not (src / "mosquitto.exe").is_file():
        print(f"WARNING: no vendored broker at {src} — run deploy/fetch-mosquitto.ps1 first. "
              "The frozen station will run but MQTT stays offline until a broker is on :1883.")
        return
    dest = DIST / "vendor" / "mosquitto" / "win64"
    shutil.copytree(src, dest, dirs_exist_ok=True)
    # Mosquitto's binaries hard-import the MSVC runtime (VCRUNTIME140.dll, +140_1 for
    # mosquittopp.dll). The official Windows build assumes the system-wide VC++ redistributable is
    # present; a genuinely clean client PC doesn't have it, so mosquitto.exe fails to launch with a
    # missing-DLL error, the broker never binds :1883, and it surfaces three layers away as a bare
    # connection-refused. build_backend() already places copies next to run.exe (DIST/, via
    # --add-binary), but Windows' DLL search checks an exe's OWN directory first, never a sibling —
    # so copy them into the broker's dir too. No new download (Issue 5).
    for name in ("vcruntime140.dll", "vcruntime140_1.dll"):
        src_dll = DIST / name
        if src_dll.is_file():
            shutil.copy2(src_dll, dest / name)
    # Build-gate: at minimum vcruntime140.dll MUST sit beside mosquitto.exe now, or a clean-PC
    # first-install ships a broker that can't start. Catch a future Mosquitto dep-set change here,
    # on the builder, instead of on a customer bench.
    if not (dest / "vcruntime140.dll").is_file():
        raise SystemExit(
            "vendored broker is missing vcruntime140.dll beside mosquitto.exe — build_backend() did "
            f"not place one in {DIST} to copy. mosquitto.exe would fail to start on a clean client "
            "PC. Ensure the backend build ran first, and that vcruntime140.dll actually exists "
            "beside the build Python's own executable (Path(sys.base_prefix)).")
    n = sum(1 for _ in dest.iterdir())
    print(f"vendored broker: deploy/vendor/mosquitto/win64 -> run.dist/vendor/mosquitto/win64 ({n} files, "
          "+ vcruntime140 beside mosquitto.exe)")


# pywebview.platforms submodules to exclude from the frozen run_station.exe on Windows.
#
# Nuitka ships a bundled `PywebViewPlugin` that intercepts every `webview.platforms.*` import and
# decides, on its own, which ones belong on this OS — its Windows allow-list is exactly
# {winforms, edgechromium, edgehtml, mshtml, cef}. That list is WRONG for our purposes on at least
# one real Nuitka/pywebview combination (Nuitka 4.1.3): `win32` is missing from it even though
# `winforms.py` (which the plugin DOES want) imports `win32.py` internally as its own helper.
# Nuitka hard-fails ("Conflict between user and plugin decision for module
# 'webview.platforms.win32'") the instant our command line and the plugin disagree about ANY
# platforms submodule — in EITHER direction (confirmed empirically: `--nofollow-import-to` it
# conflicts, and so does explicitly `--include-module`-ing it back in). There is no per-module flag
# that wins that argument; the plugin's opinion is final for any module it has one about. An
# earlier version of this function retried adaptively (expanding the exclude set from Nuitka's own
# FATAL line), which "resolves" the conflict by agreeing to exclude `win32` — the compile succeeds,
# but `winforms.py` can then never import at runtime, and the resulting exe boots its backend fine
# yet can never open a window (caught by _verify_run_station_exe's windowed check below, but not
# actually fixed by that retry — reproduced for real on a live app fork).
#
# So we don't ask the plugin. `--disable-plugin=pywebview` removes it (and its opinions) entirely,
# and we take over its one legitimate job ourselves: excluding the platforms genuinely irrelevant
# to a Windows build. `winforms` (needed), its `win32` dependency, and `edgechromium` (pywebview
# prefers this over winforms when the WebView2 runtime is present) are then included by Nuitka's
# ORDINARY static import following, same as any other module — nothing left to veto them. This is
# a fixed, version-independent list (unlike the plugin's own allow-list, the actual Python import
# graph of `winforms.py` doesn't vary by Nuitka/pywebview version), so it doesn't need the adaptive
# retry the plugin-arbitrated approach did. Confirmed live: without this, the compiled exe raised
# `ImportError: Module 'webview.platforms.win32' was actively excluded` the instant it tried to
# open a window; with it, a real window opens.
_WEBVIEW_NOFOLLOW = ("android", "cocoa", "gtk", "qt", "mshtml", "edgehtml", "cef")


def _process_has_visible_window(image_name: str) -> bool:
    """True if any VISIBLE top-level window is owned by a process whose image basename matches
    `image_name` (case-insensitive). Matches by image name, not PID: Nuitka `--onefile` is a
    bootstrap process that spawns a CHILD to run the real payload, and the window belongs to the
    child, not the PID we launched — but both carry the same exe name. Windows-only; else False."""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]; user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]; k32.CloseHandle.restype = wintypes.BOOL
    found: list = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return True
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                if Path(buf.value).name.lower() == image_name.lower():
                    found.append(hwnd)
                    return False   # stop enumerating
        finally:
            k32.CloseHandle(h)
        return True

    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]; user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return bool(found)


def _verify_run_station_exe(station_root: Path, timeout: float = 90.0) -> bool:
    """Best-effort GATE: actually RUN the frozen `run_station.exe` **windowed** (no args) from a real
    station root and confirm BOTH that it reaches `/healthz` AND that a real window appears. The
    backend boots fine right up until pywebview throws (e.g. the Nuitka/pywebview `win32` plugin
    conflict, Issue 4), so a `--no-window` /healthz probe alone "verified" an exe that could never
    open a window — it opened a console that closed itself on every launch. Checking for an actual
    window closes that blind spot. A failure here does not abort the release (see
    build_run_station_exe) — the caller downgrades the windowed launcher to "missing".

    `/healthz` answering 200 is only meaningful if it's OUR spawned process answering — refuse to
    "verify" against a stray process a dev already has bound to :8000 (silently proved a false pass).

    Note: windowed verification needs an interactive desktop session; `cut-release.ps1` builds on a
    developer machine (its own docstring), so this holds there. On a headless CI runner a window
    cannot appear — build run_station.exe on a machine with a desktop (DEPLOY_STATION.md)."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2) as r:
            if r.status < 500:
                print("run_station.exe smoke test: ABORTED — something is already answering "
                      "http://127.0.0.1:8000/healthz (a stray station already running?). Free port "
                      "8000 and rebuild; a probe against an occupied port can't verify THIS exe.")
                return False
    except OSError:
        pass   # good: the port is free, so a later 200 can only be from the process we spawn below
    exe = station_root / "run_station.exe"
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen([str(exe)], cwd=str(station_root), creationflags=flags)   # windowed
    try:
        deadline = time.time() + timeout
        booted = False
        while time.time() < deadline:
            if proc.poll() is not None:
                print(f"run_station.exe smoke test: process exited early (rc={proc.returncode})")
                return False
            if not booted:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2) as r:
                        booted = r.status == 200
                except OSError:
                    pass
            # The window is the point: the backend can boot yet pywebview never open one.
            if booted and _process_has_visible_window("run_station.exe"):
                return True
            time.sleep(1)
        if booted:
            print(f"run_station.exe smoke test: backend booted but NO window appeared within "
                  f"{timeout:.0f}s — pywebview could not open one (the 'window opens and closes' bug). "
                  "This build cannot show a UI; treating it as failed.")
        else:
            print(f"run_station.exe smoke test: timed out waiting for /healthz ({timeout:.0f}s)")
        return False
    finally:
        if proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, check=False)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass


def build_run_station_exe(jobs: int) -> bool | None:
    """Nuitka-compile the windowed launcher into a standalone **`run_station.exe`** that
    bundles pywebview + the `launcher` supervision module, so a client PC needs NO system
    Python and NO pip (frozen-offline station). It ships in the station ROOT (beside run.dist,
    NOT inside it) so it survives the updater's run.dist swap. `run.exe` is still spawned as the
    swappable backend child; run_station.exe runs `launcher.Supervisor(...).run()` in-process.

    Onefile → a single `release-build/run_station.exe`. Requires pywebview installed on the
    builder (`pip install "pywebview>=5.0"`); on Windows it renders through the WebView2 runtime
    (an OS component the installer carries — see deploy/installer.iss.template).

    FAIL-SOFT by design: run.dist (the backend + the in-app update artifact) does not need
    run_station.exe at all — only the offline first-install setup.exe does. So a compile or smoke
    failure here WARNS and returns instead of aborting the whole release; the caller (main) still
    produces run.dist + the .zip/.ksupdate, and surfaces the failure as a distinct non-zero exit so
    CI can tell (docs/DEPLOY_STATION.md: build it on a machine with the tested MSVC toolchain instead,
    e.g. the release CI runner — build-installer.ps1 treats a missing run_station.exe as "build in CI").

    Returns True (built + verified runnable), False (attempted and failed — compile, missing exe, or
    failed the runtime smoke test), or None (skipped: non-Windows, or station.py missing)."""
    import os
    if sys.platform != "win32":
        print("note: run_station.exe is a Windows target — skipping on this platform")
        return None
    station = REPO / "station.py"
    if not station.is_file():
        print(f"WARNING: {station} not found — no frozen run_station.exe built")
        return None
    # `station.py` does `import launcher`; make backend/ importable so Nuitka can bundle it.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    icon = REPO / "frontend" / "public" / "favicon.ico"

    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--assume-yes-for-downloads",
        f"--jobs={jobs}",
        "--output-dir=" + str(OUT),
        "--output-filename=run_station.exe",
        "--windows-console-mode=disable",       # kiosk: no console window
        "--include-module=launcher",            # the supervision loop (bundled, not spawned)
        "--disable-plugin=pywebview",           # see _WEBVIEW_NOFOLLOW — its own opinion is wrong
        "--include-package=webview",            # pywebview (the native window: winforms + data)
        "--nofollow-import-to=" + ",".join(f"webview.platforms.{p}" for p in _WEBVIEW_NOFOLLOW),
    ]
    # Embed the app icon so the TASKBAR icon is correct before the window opens (the window
    # title-bar icon is set at runtime via webview.start(icon=...)). A fork's own favicon.ico wins.
    if icon.is_file():
        cmd.append(f"--windows-icon-from-ico={icon}")
    cmd.append(str(station))

    print("+", " ".join(str(c) for c in cmd), flush=True)
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    print((result.stdout or "") + (result.stderr or ""))
    if result.returncode != 0:
        print(f"WARNING: run_station.exe compile FAILED (rc={result.returncode}) — run.dist is still "
              "built/usable; the in-app updater does not need run_station.exe, only the offline "
              "setup.exe does. Build it on a machine with the tested MSVC toolchain (DEPLOY_STATION.md).")
        return False
    exe = OUT / "run_station.exe"
    if not exe.is_file():
        print("WARNING: Nuitka reported success but did not produce run_station.exe "
              "(is pywebview installed? `pip install -e \"backend[release]\"`)")
        return False
    # Drop the onefile scratch trees (run_station.build / .dist / .onefile-build) so manifest()
    # doesn't hash them and package_artifact stays lean — only run_station.exe ships.
    for scratch in OUT.glob("run_station.*"):
        if scratch.is_dir():
            shutil.rmtree(scratch, ignore_errors=True)
    print(f"windowed launcher: run_station.exe -> deploy root ({exe.stat().st_size // 1024} KB) "
          "— verifying it actually boots ...")
    if not _verify_run_station_exe(OUT):
        # A compiled-but-unrunnable exe is worse than a missing one: it looks like a release asset
        # but bricks first-install. Remove it so downstream (build-installer.ps1) sees "missing" and
        # falls back to "build in CI" instead of shipping a broken setup.exe. Windows can hold the
        # just-killed onefile exe's own file lock for a short, non-deterministic moment after the
        # test process tree dies, so retry the unlink with backoff rather than fail on WinError 32.
        for i in range(1, 7):
            try:
                exe.unlink(missing_ok=True)
                break
            except OSError as unlink_exc:
                if i == 6:
                    print(f"WARNING: could not remove the unverified run_station.exe ({unlink_exc}) — "
                          "delete release-build/run_station.exe manually before packaging.")
                    break
                time.sleep(0.4 * i)
        print("WARNING: run_station.exe compiled but FAILED the runtime smoke test (backend did not "
              "reach /healthz, or no window appeared) — removed it. This backend/C-toolchain "
              "combination cannot produce a runnable windowed launcher; build it on a machine with "
              "the tested MSVC toolchain + a desktop session instead (e.g. the release CI runner). "
              "run.dist is unaffected.")
        return False
    print("run_station.exe smoke test: OK (reached /healthz and opened a window)")
    return True


def copy_app_payload(product: str) -> None:
    """Bundle the app DEFINITION into run.dist — controller.json (template), variable maps, specs,
    VERSION — plus the repo-root `instrument_libs/` (source copy; provenance only — imports use
    the copy build_backend() already bundled into run.exe via --collect-submodules).
    NEVER bundles site-specific config: no `recipes/` (site data), no instrument instances (DB
    records set on the Instruments page), no report/DB credentials (external live config)."""
    app_src = REPO / "app" / product
    if not app_src.is_dir():
        print(f"WARNING: app/{product}/ not found - no app payload bundled (framework shell only)")
        return
    dest = DIST / "app" / product
    dest.mkdir(parents=True, exist_ok=True)
    for f in ("controller.json", "VERSION"):
        if (app_src / f).is_file():
            shutil.copy2(app_src / f, dest / f)
    # definition data the controller/UI read; `portal` = the app's own manual pages, images and bundled
    # PDFs (app-owned, customer-facing — help + portal modules resolve run.dist/app/<name>/portal)
    for sub in ("maps", "specs", "portal"):
        if (app_src / sub).is_dir():
            shutil.copytree(app_src / sub, dest / sub, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    il = REPO / "instrument_libs"
    if (il / "__init__.py").is_file():
        shutil.copytree(il, DIST / "instrument_libs", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"app payload: app/{product}/ (controller.json + maps + specs; NO recipes/creds) "
          "+ instrument_libs/ (provenance copy — imports use the bundled copy in run.exe)")


def _sanitize_config(obj, _dropped: list):
    """Strip site-secret connection credentials so a shipped app.example.json is safe: report/DB
    connection fields (a dict declaring provider/database/odbc_driver) and any token/secret/api_key.
    The auth `users` block (dev admin/admin seed — a dict with `role`) is KEPT, matching the
    framework's own app.example.json convention; real users are set out-of-band in production."""
    if isinstance(obj, dict):
        is_db = bool(set(obj) & {"provider", "database", "odbc_driver"}) and "role" not in obj
        out = {}
        for k, v in obj.items():
            if k.lower() in {"token", "secret", "api_key"} or (
                    is_db and k.lower() in {"password", "user", "username", "host", "port", "database"}):
                _dropped.append(k)
                continue
            out[k] = _sanitize_config(v, _dropped)
        return out
    if isinstance(obj, list):
        return [_sanitize_config(v, _dropped) for v in obj]
    return obj


def promote_app_config(app_config: str | None) -> None:
    """Ship the app's real branding + controller block + module STRUCTURE as the bundled
    config/app.example.json (which ensure_live copies to external live on first boot). Source:
    --app-config, else backend/config/app.release.json. Credentials are stripped; if none is
    found the generic framework example ships and the frozen app boots only the shell."""
    src = Path(app_config) if app_config else (BACKEND / "config" / "app.release.json")
    if not src.is_file():
        print(f"WARNING: no app release config ({src}) - shipping the generic framework example; "
              "the frozen app boots the SHELL only. Provide backend/config/app.release.json "
              "(non-secret branding + controller block) or pass --app-config.")
        return
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"WARNING: {src.name} is not valid JSON ({exc}) - shipping the generic example")
        return
    dropped: list = []
    clean = _sanitize_config(data, dropped)
    dest = DIST / "config" / "app.example.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    note = f" (stripped site secrets: {sorted(set(dropped))})" if dropped else ""
    print(f"app config: {src.name} -> run.dist/config/app.example.json{note}")


def _framework_version() -> str:
    init = (BACKEND / "core" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.M)
    return m.group(1) if m else "0.0.0"


def _app_version(product: str, override: str | None) -> str | None:
    """An app's OWN version (independent semver, starts 1.0.0) — from --app-version or the
    app-owned `app/<product>/VERSION` file. The framework version is provenance, not this."""
    if override:
        return override.strip()
    vf = REPO / "app" / product / "VERSION"
    if vf.is_file():
        return (vf.read_text(encoding="utf-8").strip() or None)
    return None


def manifest(track: str = "framework", product: str = "super_test_app",
             pinned_fw_version: str | None = None, app_version: str | None = None) -> None:
    fw = _framework_version()
    # An APP versions independently (its VERSION); a FRAMEWORK build uses core.__version__.
    version = app_version if (track == "app" and app_version) else fw
    entries = {}
    for f in sorted(OUT.rglob("*")):
        if f.is_file() and f.name != "RELEASE.json":
            entries[str(f.relative_to(OUT)).replace("\\", "/")] = hashlib.sha256(
                f.read_bytes()).hexdigest()
    rel = {
        "product": product, "track": track, "runtime": "python_framework",
        "version": version, "framework_version": fw, "built_at": int(time.time()),
        "files": len(entries), "sha256": entries,
    }
    if track == "app":
        # the framework version this app is built upon (provenance; TEMPLATE.md two-tier).
        rel["pinned_fw_version"] = pinned_fw_version or fw
    (OUT / "RELEASE.json").write_text(json.dumps(rel, indent=2), encoding="utf-8")
    prov = f" (framework {fw})" if track == "app" else ""
    print(f"RELEASE.json: {track} {product} v{version}{prov}, {len(entries)} files hashed")


def package_artifact(product: str) -> None:
    """Zip the compiled `run.dist` (the launcher's swap unit) and stamp its SHA-256 into
    RELEASE.json as `full_artifact_hash` — the hash the station verifies a downloaded
    artifact against before staging it (UPDATES.md _materialize; §3 GitHub-release asset).
    Runs AFTER manifest() so the zip isn't hashed into the per-file table."""
    rel_path = OUT / "RELEASE.json"
    rel = json.loads(rel_path.read_text(encoding="utf-8"))
    base = OUT / f"{product}-{rel['version']}"
    archive = Path(shutil.make_archive(str(base), "zip", root_dir=str(DIST)))
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    rel["full_artifact_hash"] = sha
    rel["artifact"] = archive.name
    rel_path.write_text(json.dumps(rel, indent=2), encoding="utf-8")
    print(f"artifact: {archive.name} ({archive.stat().st_size // 1024} KB, sha {sha[:12]}…)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-frontend", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--track", choices=["framework", "app"], default="framework",
                    help="release tier (app repos pass --track app)")
    ap.add_argument("--product", default="super_test_app",
                    help="Keystation product slug (app repos pass their app-track slug)")
    ap.add_argument("--pinned-fw-version", default=None,
                    help="framework version an app build was built upon (defaults to the "
                         "framework's core.__version__)")
    ap.add_argument("--app-version", default=None,
                    help="the app's OWN version (defaults to app/<product>/VERSION); app track only")
    ap.add_argument("--app-config", default=None,
                    help="non-secret app config shipped as config/app.example.json (app track; "
                         "defaults to backend/config/app.release.json)")
    ap.add_argument("--manifest-only", action="store_true",
                    help="re-hash an existing release-build (no recompile)")
    args = ap.parse_args()

    app_ver = _app_version(args.product, args.app_version) if args.track == "app" else None
    if args.track == "app" and not app_ver:
        ap.error(f"--track app needs the app version — create app/{args.product}/VERSION "
                 "(e.g. 1.0.0) or pass --app-version")

    if args.manifest_only:
        manifest(args.track, args.product, args.pinned_fw_version, app_ver)
        return 0

    if OUT.exists():
        shutil.rmtree(OUT)
    build_backend(args.track, args.product)
    if args.track == "app":
        # run.exe doubles as the controller (`run.exe --controller`). Verify it can start as one
        # BEFORE spending time on data/config/zip — fail fast on a mis-bundled toolchain.
        _verify_frozen_controller(args.product)
    copy_data()
    copy_docs_frontend_dll(args.skip_frontend)
    run_station_ok: bool | None = None
    if args.track == "app":
        # A runnable app = the backend exe (which also runs the controller) + the app definition +
        # drivers, all inside run.dist so an update swap carries the whole thing (SECURE_DISTRIBUTION §5).
        copy_app_payload(args.product)
        promote_app_config(args.app_config)
        copy_vendor_broker()            # vendored Mosquitto INSIDE run.dist (no service, no admin)
        # FAIL-SOFT (see build_run_station_exe docstring): run.dist + the .zip/.ksupdate are still
        # produced below even if the frozen windowed launcher can't be built/verified here — only the
        # offline first-install setup.exe needs run_station.exe, not the in-app update path.
        run_station_ok = build_run_station_exe(args.jobs)  # BESIDE run.dist (no Python/pip on client)
    manifest(args.track, args.product, args.pinned_fw_version, app_ver)
    # RELEASE.json must ride INSIDE run.dist (the swap unit) so an applied update swaps the
    # version manifest too; app_version() reads run.dist/RELEASE.json first (core.__init__).
    # Copied AFTER manifest() (which excludes RELEASE.json from its hash table by name) and
    # BEFORE package_artifact() (so the zipped swap unit carries it).
    shutil.copy2(OUT / "RELEASE.json", DIST / "RELEASE.json")
    package_artifact(args.product)
    print("\nrelease at:", OUT)
    if run_station_ok is False:
        RUN_STATION_EXE_FAILED = 3   # distinct from a hard build failure (which raises/exits nonzero earlier)
        print("\nWARNING: run.dist + the update artifact are ready, but run_station.exe did NOT build "
              "or did not pass its runtime smoke test — see the WARNING above. The offline setup.exe "
              "cannot be built from THIS run-station.exe; build it on a machine with the tested MSVC "
              "toolchain (e.g. the release CI runner), or fall back to install-station.ps1.")
        return RUN_STATION_EXE_FAILED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

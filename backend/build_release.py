"""Release build — Nuitka-compiled backend (secure distribution P2).

Compiles the Python backend to native code (Python -> C -> machine code): real IP
protection for the framework + instrument logic, and exactly the artifact shape
Keystation's `python_framework` FRAMEWORK track distributes. PyInstaller
(`tmf-sidecar.spec`) remains for quick dev bundles only.

Output layout (SECURE_DISTRIBUTION.md §5):

    release-build/
      run.dist/            compiled backend (run.exe + native libs) = the swap unit + the .zip
        launcher.py        update supervisor (catches exit-42, applies the staged run.dist)
        modules/**         manifest.json / schemas / step_types / known_issues (data)
        core/schemas/*     app/license schema JSON (data)
        config/*.example.json
        frontend/          built SPA (served single-origin; resolve_frontend_dist prefers this)
        docs/              in-app help markdown (help.catalog resolves this first)
        --- app track (--track app): run.exe ALSO runs the controller (run.exe --controller),
            and these bundle INSIDE run.dist so a swap carries it all: ---
        app/<product>/     app DEFINITION: controller.json, maps/, specs/ (NO recipes/creds)
        instrument_libs/   copied drivers (provenance; imports use the compiled-in copy)
        vendor/mosquitto/  vendored broker (win64: mosquitto.exe + DLLs + loopback conf) — the
                           frozen station starts its OWN broker: no Mosquitto install/service/admin
      run_station.exe      frozen windowed launcher (deploy root, BESIDE run.dist) — bundles
                           pywebview + the launcher module: client needs NO Python/pip. Its own
                           release asset; survives the run.dist swap because it's a sibling.
      run_station.py       windowed launcher SOURCE (deploy root; kept for the scripted fallback)
      keystation_core.dll  native licensing core (app.json licensing.core_lib)
      RELEASE.json         version + SHA-256 manifest of the above
    Everything the running app SERVES (UI, help, app def, drivers) is inside run.dist, so the
    published <slug>-<ver>.zip is a complete app AND an in-app update refreshes all of it.

Usage:  python build_release.py [--track framework|app] [--product <name>]
                                 [--app-config <path>] [--skip-frontend] [--jobs N] [--mingw64]
App track compiles ONE exe: run.exe also runs the controller (`run.exe --controller`) with the
app's step-type packages + instrument_libs compiled in (import-by-name), so a frozen app runs its
OWN test sequence — not just the shell. (One exe, because a lean separately-compiled controller.exe
fails to bundle the stdlib on Nuitka's zig backend; run.exe's large graph always pulls it in.)
Compiler backend defaults to MSVC (`cl`) + clcache — an object cache, so a WARM rebuild is fast
(unchanged objects are cache hits). `--mingw64` opts into gcc + ccache (needs a working MinGW,
unavailable on Python 3.13+).
The signed Keystation framework-release registration (manifest + build_timestamp)
happens in CI / on the issuer, not here — this script only produces + hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def _compiler_args(mingw: bool) -> list[str]:
    """Compiler backend for Nuitka. Default (empty) lets Nuitka pick **MSVC (`cl`)** on Windows,
    which it drives through **clcache** — an object cache, so a WARM rebuild is fast (unchanged
    `.obj` are cache hits; only your changed app packages recompile). `--mingw64` opts into
    **gcc + ccache** instead, which needs a WORKING MinGW: Nuitka's auto-downloaded gcc 15.2.0 ships
    a broken Windows SDK header (`psdk_inc/intrin-impl.h`) on some setups and fails the C compile —
    install a known-good MinGW (e.g. winlibs gcc 13.x) and put it on PATH, or stay on the MSVC
    default. Both back ends cache objects; the default just works out of the box here."""
    if mingw:
        if sys.version_info >= (3, 13):
            raise SystemExit(
                "--mingw64 is unsupported on Python 3.13+ (Nuitka rejects it, and refuses an "
                "external winlibs gcc). Use the default MSVC backend, or build on Python <=3.12.")
        return ["--mingw64"]
    return []


def _app_build_env(product: str) -> dict:
    """Nuitka resolves `--include-package` against sys.path, so put the app's package roots on
    PYTHONPATH: the repo root (for `instrument_libs`), `app/<product>` (for `<name>_steps`), and
    `controller/` (the `controller` package the recipe catalog imports)."""
    import os
    roots = os.pathsep.join([str(REPO), str(REPO / "app" / product), str(REPO / "controller")])
    env = dict(os.environ)
    env["PYTHONPATH"] = roots + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _app_include_packages(product: str) -> list[str]:
    """The app's dynamically-named packages to compile into the exes — read from
    `app/<product>/controller.json` (`step_type_packages` + `library_packages`) plus the repo-root
    `instrument_libs/` (copied drivers). They load by NAME at runtime (import_module), invisible to
    static analysis, so each must be force-included."""
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


def build_backend(jobs: int, track: str = "framework", product: str = "super_test_app",
                  mingw: bool = False) -> None:
    import importlib.util
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        *_compiler_args(mingw),
        f"--jobs={jobs}",
        "--output-dir=" + str(OUT),
        # dynamic discovery (core.framework.registry.discover) is invisible to
        # static analysis - force-compile the whole tree:
        "--include-package=core",
        "--include-package=modules",
        # C-extension / runtime deps that static analysis can miss:
        "--include-package=argon2",
        "--include-package=uvicorn",
        "--include-package=aiosqlite",
        "--include-package=sqlalchemy",
    ]
    # keystation SDK is optional + deployment-specific (external repo, ships with the
    # SDK+DLL). Bundle it only when installed; the provider lazy-imports it otherwise.
    for opt in ("keystation",):
        if importlib.util.find_spec(opt) is not None:
            cmd.append(f"--include-package={opt}")
        else:
            print(f"note: '{opt}' not installed - not bundled (added at deployment)")
    env = None
    if track == "app":
        # The recipe module builds its catalog via `from controller.packages import …`
        # (modules/recipe/catalog.py), so the CONTROLLER package must be compiled into the
        # backend too — plus the app's step-type packages + drivers (import-by-name).
        cmd.append("--include-package=controller")
        for pkg in _app_include_packages(product):
            cmd += [f"--include-package={pkg}", f"--include-package-data={pkg}"]
        env = _app_build_env(product)
    cmd.append("run.py")
    _run(cmd, cwd=BACKEND, env=env)


def _verify_frozen_controller(product: str) -> None:
    """GATE: the frozen backend exe MUST also run as the controller (`run.exe --controller`) — load
    the app's step packages, pass the conformance re-check, build the registry, and reach
    `instruments:` with no crash. Catches frozen-only failures (stdlib not bundled →
    `Failed to import encodings`; `inspect.getsource` in the conformance gate → `could not get
    source`). Launch with a real config + an unreachable broker so it can't hang, and FAIL the whole
    build if the controller can't start — a frozen app that boots the UI but can't run the controller
    is a FAIL. Runs for --track app right after the backend compile (fail fast, one exe)."""
    import tempfile
    exe = DIST / ("run.exe" if sys.platform == "win32" else "run.bin")
    if not exe.exists():
        exe = DIST / "run"
    steps = [p for p in _app_include_packages(product) if p != "instrument_libs"]
    cfg = {"schema_version": 1, "broker": {"host": "127.0.0.1", "port": 9},   # port 9 = discard
           "step_type_packages": steps, "stations": [{"station": "st1"}], "simulation": False}
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
            "  A frozen app that boots the UI but can't run the controller is a FAIL. On an "
            "MSVC-less builder Nuitka may mis-bundle the stdlib for lean graphs — installing VS "
            "'Desktop development with C++' (or standalone Build Tools) gives the tested backend.")


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


def copy_docs_frontend_dll(skip_frontend: bool) -> None:
    # The SPA + in-app help ride INSIDE run.dist (the swap unit), so the published .zip is a
    # COMPLETE app (a client install has the UI) AND an in-app update refreshes the UI/help too —
    # a swap replaces run.dist wholesale. The fork's OWN `frontend/dist` (built here) already
    # contains its custom screen overrides (frontend/src/app/overrides/*), so they ship automatically.
    # spa.py / help.catalog resolve run.dist/{frontend,docs} first (v1.12.0).
    shutil.copytree(REPO / "docs", DIST / "docs", dirs_exist_ok=True)
    if not skip_frontend:
        fe = REPO / "frontend" / "dist"
        if not fe.exists():
            _run(["npm", "run", "build"], cwd=REPO / "frontend")   # builds the fork's UI incl. overrides
        shutil.copytree(fe, DIST / "frontend", dirs_exist_ok=True)
    # Windowed launcher — a small deploy-root script (NOT the swap unit; it launches run.dist). It is
    # published as its own tiny release asset so install-station.ps1 can place it beside run.dist.
    win_entry = REPO / "run_station.py"
    if win_entry.is_file():
        shutil.copy2(win_entry, OUT / "run_station.py")
        print("windowed entry: run_station.py -> deploy root")
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
    n = sum(1 for _ in dest.iterdir())
    print(f"vendored broker: deploy/vendor/mosquitto/win64 -> run.dist/vendor/mosquitto/win64 ({n} files)")


def build_run_station_exe(jobs: int) -> None:
    """Nuitka-compile the windowed launcher into a standalone **`run_station.exe`** that
    bundles pywebview + the `launcher` supervision module, so a client PC needs NO system
    Python and NO pip (frozen-offline station). It ships in the station ROOT (beside run.dist,
    NOT inside it) so it survives the updater's run.dist swap. `run.exe` is still spawned as the
    swappable backend child; run_station.exe runs `launcher.Supervisor(...).run()` in-process.

    Onefile → a single `release-build/run_station.exe`. Requires pywebview installed on the
    builder (`pip install "pywebview>=5.0"`); on Windows it renders through the WebView2 runtime
    (an OS component the installer carries — see deploy/installer.iss.template)."""
    import os
    if sys.platform != "win32":
        print("note: run_station.exe is a Windows target — skipping on this platform")
        return
    run_station = REPO / "run_station.py"
    if not run_station.is_file():
        print(f"WARNING: {run_station} not found — no frozen run_station.exe built")
        return
    # `run_station.py` does `import launcher`; make backend/ importable so Nuitka can bundle it.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--assume-yes-for-downloads",
        f"--jobs={jobs}",
        "--output-dir=" + str(OUT),
        "--output-filename=run_station.exe",
        "--windows-console-mode=disable",          # kiosk: no console window
        "--include-module=launcher",               # the supervision loop (bundled, not spawned)
        "--include-package=webview",               # pywebview (the native window)
        str(run_station),
    ]
    _run(cmd, cwd=REPO, env=env)
    exe = OUT / "run_station.exe"
    if not exe.is_file():
        raise SystemExit("BUILD FAILED: Nuitka did not produce run_station.exe (is pywebview installed?)")
    # Drop the onefile scratch trees (run_station.build / .dist / .onefile-build) so manifest()
    # doesn't hash them and package_artifact stays lean — only run_station.exe ships.
    for scratch in OUT.glob("run_station.*"):
        if scratch.is_dir():
            shutil.rmtree(scratch, ignore_errors=True)
    print(f"windowed launcher: run_station.exe -> deploy root ({exe.stat().st_size // 1024} KB)")


def copy_app_payload(product: str) -> None:
    """Bundle the app DEFINITION into run.dist — controller.json (template), variable maps, specs,
    VERSION — plus the repo-root `instrument_libs/` (provenance; imports use the compiled-in copy).
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
    for sub in ("maps", "specs"):                       # definition data the controller/UI read
        if (app_src / sub).is_dir():
            shutil.copytree(app_src / sub, dest / sub, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    il = REPO / "instrument_libs"
    if (il / "__init__.py").is_file():
        shutil.copytree(il, DIST / "instrument_libs", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"app payload: app/{product}/ (controller.json + maps + specs; NO recipes/creds) "
          "+ instrument_libs/")


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
    import re
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
    ap.add_argument("--mingw64", action="store_true",
                    help="use the MinGW64 + ccache backend instead of the default MSVC + clcache "
                         "(needs a working MinGW on PATH — see _compiler_args)")
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
    build_backend(args.jobs, args.track, args.product, args.mingw64)
    if args.track == "app":
        # run.exe doubles as the controller (`run.exe --controller`). Verify it can start as one
        # BEFORE spending time on data/payload/zip — fail fast on a mis-bundled toolchain.
        _verify_frozen_controller(args.product)
    copy_data()
    copy_docs_frontend_dll(args.skip_frontend)
    if args.track == "app":
        # A runnable app = the backend exe (which also runs the controller) + the app definition +
        # drivers, all inside run.dist so an update swap carries the whole thing (SECURE_DISTRIBUTION §5).
        copy_app_payload(args.product)
        promote_app_config(args.app_config)
        copy_vendor_broker()            # vendored Mosquitto INSIDE run.dist (no service, no admin)
        build_run_station_exe(args.jobs)  # frozen windowed launcher BESIDE run.dist (no Python/pip)
    manifest(args.track, args.product, args.pinned_fw_version, app_ver)
    # RELEASE.json must ride INSIDE run.dist (the swap unit) so an applied update swaps the
    # version manifest too; app_version() reads run.dist/RELEASE.json first (core.__init__).
    # Copied AFTER manifest() (which excludes RELEASE.json from its hash table by name) and
    # BEFORE package_artifact() (so the zipped swap unit carries it).
    shutil.copy2(OUT / "RELEASE.json", DIST / "RELEASE.json")
    package_artifact(args.product)
    print("\nrelease at:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Release build — Nuitka-compiled backend (secure distribution P2).

Compiles the Python backend to native code (Python -> C -> machine code): real IP
protection for the framework + instrument logic, and exactly the artifact shape
Keystation's `python_framework` FRAMEWORK track distributes. PyInstaller
(`tmf-sidecar.spec`) remains for quick dev bundles only.

Output layout (SECURE_DISTRIBUTION.md §5):

    release-build/
      run.dist/            compiled backend (run.exe + native libs) = the swap unit
        launcher.py        update supervisor (catches exit-42, applies the staged run.dist)
        modules/**         manifest.json / schemas / step_types / known_issues (data)
        core/schemas/*     app/license schema JSON (data)
        config/*.example.json
        --- app track (--track app) also bundles, INSIDE run.dist so a swap carries it all: ---
        controller.dist/   compiled Python controller (controller.exe + app step packages)
        app/<product>/     app DEFINITION: controller.json, maps/, specs/ (NO recipes/creds)
        instrument_libs/   copied drivers (provenance; imports use the compiled-in copy)
      docs/                in-app help markdown (help catalog resolves ../docs)
      frontend/            built SPA (serve statically at the station)
      keystation_core.dll  native licensing core (app.json licensing.core_lib)
      RELEASE.json         version + SHA-256 manifest of the above

Usage:  python build_release.py [--track framework|app] [--product <name>]
                                 [--app-config <path>] [--skip-frontend] [--jobs N]
App track compiles a SECOND exe (the controller) with the app's step-type packages +
instrument_libs (import-by-name), so a frozen app runs its OWN test sequence — not just the shell.
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


def build_backend(jobs: int, track: str = "framework", product: str = "super_test_app") -> None:
    import importlib.util
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
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


def build_controller(jobs: int, product: str) -> None:
    """Nuitka-compile the Python controller into `run.dist/controller.dist/controller.exe`, with the
    app's step-type packages + `instrument_libs` compiled in (they load by name via config). The
    supervisor's frozen branch (controller_supervisor._command) finds it at that path."""
    ctrl_repo = REPO / "controller"
    entry = ctrl_repo / "controller" / "__main__.py"
    if not entry.is_file():
        print("WARNING: controller package not found - controller.exe NOT built (app can't run tests)")
        return
    stage = OUT / "_controller_build"
    cmd = [
        sys.executable, "-m", "nuitka", "--standalone", "--assume-yes-for-downloads",
        f"--jobs={jobs}", "--output-dir=" + str(stage),
        "--include-package=controller",
    ]
    for pkg in _app_include_packages(product):
        cmd += [f"--include-package={pkg}", f"--include-package-data={pkg}"]
    cmd.append(str(entry))
    _run(cmd, cwd=ctrl_repo, env=_app_build_env(product))
    # Nuitka names the output after the entry file (__main__.dist / __main__.exe). Normalize to
    # controller.dist/controller.exe and move it INTO run.dist (the swap unit).
    built = stage / "__main__.dist"
    exe = "controller.exe" if sys.platform == "win32" else "controller"
    src_exe = built / ("__main__.exe" if sys.platform == "win32" else "__main__.bin")
    if src_exe.exists():
        src_exe.rename(built / exe)
    dest = DIST / "controller.dist"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(built), str(dest))
    shutil.rmtree(stage, ignore_errors=True)
    print(f"controller: controller.dist/{exe} -> run.dist/")


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
    # in-app help: catalog.py resolves <dist parent>/docs
    shutil.copytree(REPO / "docs", OUT / "docs", dirs_exist_ok=True)
    if not skip_frontend:
        fe = REPO / "frontend" / "dist"
        if not fe.exists():
            _run(["npm", "run", "build"], cwd=REPO / "frontend")
        shutil.copytree(fe, OUT / "frontend", dirs_exist_ok=True)
    # Windowed entry for the frozen deploy — sits at the deploy root (NOT inside run.dist,
    # so a swap never replaces it); supervises run.dist/launcher.py + opens a pywebview window.
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
    build_backend(args.jobs, args.track, args.product)
    copy_data()
    copy_docs_frontend_dll(args.skip_frontend)
    if args.track == "app":
        # A runnable app = backend + the Python controller + the app definition + drivers, all
        # inside run.dist so an update swap carries the whole thing (SECURE_DISTRIBUTION.md §5).
        build_controller(args.jobs, args.product)
        copy_app_payload(args.product)
        promote_app_config(args.app_config)
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

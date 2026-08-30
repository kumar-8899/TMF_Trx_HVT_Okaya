"""Release build — Nuitka-compiled backend (secure distribution P2).

Compiles the Python backend to native code (Python -> C -> machine code): real IP
protection for the framework + instrument logic, and exactly the artifact shape
Keystation's `python_framework` FRAMEWORK track distributes. PyInstaller
(`tmf-sidecar.spec`) remains for quick dev bundles only.

Output layout (SECURE_DISTRIBUTION.md §5):

    release-build/
      run.dist/            compiled backend (run.exe + native libs)
        modules/**         manifest.json / schemas / step_types / known_issues (data)
        core/schemas/*     app/license schema JSON (data)
        config/*.example.json
      docs/                in-app help markdown (help catalog resolves ../docs)
      frontend/            built SPA (serve statically at the station)
      keystation_core.dll  native licensing core (app.json licensing.core_lib)
      RELEASE.json         version + SHA-256 manifest of the above

Usage:  python build_release.py [--skip-frontend] [--jobs N]
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


def _run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def build_backend(jobs: int) -> None:
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
    cmd.append("run.py")
    _run(cmd, cwd=BACKEND)


def copy_data() -> None:
    n = 0
    for pattern in DATA_PATTERNS:
        for src in BACKEND.glob(pattern):
            dest = DIST / src.relative_to(BACKEND)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            n += 1
    print(f"data files: {n}")


def copy_docs_frontend_dll(skip_frontend: bool) -> None:
    # in-app help: catalog.py resolves <dist parent>/docs
    shutil.copytree(REPO / "docs", OUT / "docs", dirs_exist_ok=True)
    if not skip_frontend:
        fe = REPO / "frontend" / "dist"
        if not fe.exists():
            _run(["npm", "run", "build"], cwd=REPO / "frontend")
        shutil.copytree(fe, OUT / "frontend", dirs_exist_ok=True)
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
    build_backend(args.jobs)
    copy_data()
    copy_docs_frontend_dll(args.skip_frontend)
    manifest(args.track, args.product, args.pinned_fw_version, app_ver)
    package_artifact(args.product)
    print("\nrelease at:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

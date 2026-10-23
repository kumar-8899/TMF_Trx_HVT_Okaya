"""Release-gate helper (D10): prove the BUILT SPA is not stale.

`build_release.py` stamps `run.dist/frontend/build-info.json` = {app_version, git_sha, src_hash}
right after `npm run build`. This recomputes the same facts from the tree being released and fails
when they differ, so a bundle built from older sources (e.g. `cut-release.ps1 -SkipTests` used to skip
the only UI build) can never ship. With --url it also fetches the stamp from the RUNNING app, proving
the exe serves that bundle.

Usage: python verify_frontend_stamp.py <run.dist dir> <slug> [--url http://127.0.0.1:18765]
Exit 0 = ok, 1 = stale / mismatch / missing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _git_sha(repo: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def check(dist: Path, slug: str, *, repo: Path = REPO, sha: str | None = None) -> list[str]:
    sys.path.insert(0, str(REPO / "backend"))
    try:
        import build_release as br
    finally:
        sys.path.pop(0)
    old = br.REPO
    br.REPO = repo                                  # hash the tree we were told to verify
    try:
        want_hash = br.frontend_src_hash()
    finally:
        br.REPO = old
    p = dist / "frontend" / "build-info.json"
    if not p.is_file():
        return [f"{p} missing - the SPA was not built/stamped by build_release.py"]
    stamp = json.loads(p.read_text(encoding="utf-8"))
    errs = []
    if stamp.get("src_hash") != want_hash:
        errs.append("stale UI: the bundled frontend was built from different sources than the tree "
                    "being released (src_hash differs) - rebuild (npm run build) and re-cut")
    vf = repo / "app" / slug / "VERSION"
    if vf.is_file():
        want_ver = vf.read_text(encoding="utf-8").strip()
        if stamp.get("app_version") != want_ver:
            errs.append(f"UI stamped app_version {stamp.get('app_version')!r} != app/{slug}/VERSION {want_ver!r}")
    sha = sha if sha is not None else _git_sha(repo)
    if stamp.get("git_sha") != sha:
        errs.append(f"UI stamped git sha {stamp.get('git_sha')!r} != HEAD {sha!r} (built from another commit)")
    return errs


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: verify_frontend_stamp.py <run.dist> <slug> [--url BASE]")
        return 2
    dist, slug = Path(argv[0]), argv[1]
    errs = check(dist, slug)
    if "--url" in argv:
        base = argv[argv.index("--url") + 1].rstrip("/")
        try:
            with urllib.request.urlopen(base + "/build-info.json", timeout=10) as r:
                live = json.loads(r.read().decode("utf-8"))
            disk = json.loads((dist / "frontend" / "build-info.json").read_text(encoding="utf-8"))
            if live != disk:
                errs.append(f"the running app serves a different UI stamp than run.dist/frontend: {live} vs {disk}")
        except Exception as exc:  # noqa: BLE001
            errs.append(f"could not fetch {base}/build-info.json from the running app: {exc}")
    for e in errs:
        print(f"FAIL  {e}")
    if not errs:
        print("ok    UI bundle matches sources + version + commit")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

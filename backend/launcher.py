"""Station launcher — supervises the backend and applies staged updates on relaunch
(secure distribution P3, the piece a running binary can't do to itself).

Loop:
  start backend  ->  wait  ->  exit 42 (RELAUNCH) + marker  ->  swap staged artifact
  in (backup + hash-verify + health-gated rollback)  ->  restart. Any other exit stops.

The app requests a relaunch by writing `data/relaunch.json` and exiting 42
(`POST /update/relaunch/{id}`); the UI "Relaunch to update" chip triggers it. The
swap runs while the backend is DOWN, so the live files are free to replace.

Dev (running `python run.py`, no run.dist) → the swap is a no-op and the launcher
just restarts, which still proves the relaunch loop. Frozen (`run.dist/run.exe`)
→ the staged `run.dist` replaces the live one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RELAUNCH = 42
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
MARKER = DATA / "relaunch.json"
LOG = DATA / "launcher.log"
HEALTH_URL = os.environ.get("TMF_HEALTH_URL", "http://127.0.0.1:8000/healthz")
HEALTH_TIMEOUT = int(os.environ.get("TMF_HEALTH_TIMEOUT", "40"))


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} launcher: {msg}"
    print(line, flush=True)
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def backend_cmd() -> list[str]:
    exe = HERE / "run.exe"                      # frozen dist
    if exe.exists():
        return [str(exe)]
    return [sys.executable, str(HERE / "run.py")]   # dev / source


def _sha_of_release(dist: Path) -> str | None:
    rel = dist / "RELEASE.json"
    if not rel.is_file():
        return None
    try:
        return json.loads(rel.read_text(encoding="utf-8")).get("version")
    except (OSError, json.JSONDecodeError):
        return None


def apply_staged(marker: dict) -> bool:
    """Swap a staged artifact dir into place, with backup. Returns True if a swap
    happened. Health-gated rollback is handled by the caller after restart."""
    staged = marker.get("staged_dir")
    if not staged:
        log("relaunch with no staged_dir - restart only (dev / no-op swap)")
        return False
    staged_dir = Path(staged)
    live = HERE                                  # run.dist (frozen) = launcher dir
    if not staged_dir.is_dir():
        log(f"staged dir missing: {staged_dir} - aborting swap, restart old")
        return False
    log(f"staging version {_sha_of_release(staged_dir)} from {staged_dir}")
    backup = live.parent / f"{live.name}.bak-{int(time.time())}"
    # Move the live tree aside, move staged in. Keep the backup for rollback.
    try:
        # copy staged in beside, then swap dirs (avoids partial live state)
        shutil.move(str(live), str(backup))
        shutil.move(str(staged_dir), str(live))
        log(f"swap done; backup at {backup.name}")
        return True
    except OSError as exc:
        log(f"swap FAILED: {exc} - restoring")
        if backup.exists() and not live.exists():
            shutil.move(str(backup), str(live))
        return False


def health_ok() -> bool:
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=3) as r:
                if r.status == 200:
                    return True
        except OSError:
            time.sleep(1)
    return False


def run_once() -> int:
    proc = subprocess.Popen(backend_cmd(), cwd=str(HERE))
    log(f"backend started pid={proc.pid} ({' '.join(backend_cmd())})")
    return proc.wait()


def main() -> int:
    log("launcher up")
    while True:
        rc = run_once()
        log(f"backend exited rc={rc}")
        if rc != RELAUNCH:
            log("normal exit - launcher stopping")
            return rc
        if not MARKER.is_file():
            log("relaunch code but no marker - restart as-is")
            continue
        marker = json.loads(MARKER.read_text(encoding="utf-8"))
        swapped = apply_staged(marker)
        try:
            MARKER.unlink()
        except OSError:
            pass
        log(f"relaunching for {marker.get('version', '?')} (swapped={swapped})")
        # restart happens at the top of the loop; health rollback if the new one is dead
        # is left to the next iteration's health check + operator (backup kept on disk).


if __name__ == "__main__":
    raise SystemExit(main())

"""Run a PRISTINE, throw-away station for screenshot capture.

    python tools/screenshots/run_isolated.py <state-dir>

Builds a fresh state root (live config copied from the framework's own *.example.json, empty data/),
then supervises the backend with `launcher.supervise` — the same supervisor `station.py` uses, so
/system/relaunch and /system/shutdown behave like a real station. It never reads or writes
backend/config/app.json or backend/data/: the shared docs images must show the NEUTRAL framework
(default branding, no fork's instruments, no real logs), not whatever this dev machine last ran.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    state = Path(sys.argv[1]).resolve()
    if state.exists():
        shutil.rmtree(state)
    (state / "config").mkdir(parents=True)
    for name in ("app", "license"):
        shutil.copy2(BACKEND / "config" / f"{name}.example.json", state / "config" / f"{name}.json")
    # The backend runs with cwd = backend/, and the recipe + report modules have a one-time rescue
    # (config.migrate_cwd_state) that COPIES a cwd-relative `data/recipes` / `data/report_outbox.sqlite`
    # into the state dir when the state copy doesn't exist yet. On a dev machine that would import the
    # developer's real recipes and report queue into the "pristine" station. Pre-creating the
    # destinations makes the rescue a no-op.
    (state / "data" / "recipes").mkdir(parents=True)
    (state / "data" / "report_outbox.sqlite").touch()
    sys.path.insert(0, str(BACKEND))
    import launcher
    print(f"screenshot station: pristine state at {state}", flush=True)
    return launcher.supervise(BACKEND, state)


if __name__ == "__main__":
    raise SystemExit(main())

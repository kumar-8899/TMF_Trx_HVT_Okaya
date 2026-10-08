"""Debug Server entrypoint (DEBUG_SERVER.md §2). Standalone sidecar.

    python run_debug_server.py            # broker 127.0.0.1:1883, UI on :8001
    run.exe --debug-server                # the same, from an installed (frozen) build
    TMF_DEBUG_NO_AUTH=1 python run_debug_server.py   # skip token check (dev only)

The implementation lives in `debug_server.entry` so the frozen `run.exe` can dispatch to it
(`backend/run.py`, FRAMEWORK CR A2); this file stays the source-tree launcher.
"""

from __future__ import annotations

from debug_server.entry import main

if __name__ == "__main__":
    main()

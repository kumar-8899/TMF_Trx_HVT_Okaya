"""Backend entry point — serves the FastAPI app via uvicorn.

Triple entry: the SAME frozen `run.exe` also runs the Python **controller**
(`run.exe --controller <config>`) and the **flight recorder** sidecar (`run.exe --debug-server`, the
Debug Server of docs/REMOTE_DEBUG.md - so a client PC can be recorded, not only a dev checkout), so an
app-track build needs only ONE compiled exe. The
controller then reuses `run.exe`'s stdlib — a lean, separately-compiled controller.exe fails to
bundle the pure-Python stdlib (encodings/threading) on Nuitka's zig backend (MSVC-less builders),
whereas the backend's large import graph always pulls the stdlib in. The controller supervisor
spawns this form in a frozen build (`core.services.controller_supervisor`).

The `app` object is imported directly (not by string) so the compiler bundles the `core`
package; business modules are discovered dynamically at runtime and force-compiled by
`build_release.py` (`--include-package`), not by static analysis here.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import sys


def main() -> int | None:
    # aiomqtt (paho) needs a selector loop; Windows defaults to Proactor. Both modes need it.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    argv = sys.argv[1:]
    if argv and argv[0] == "--controller":
        # Controller mode — dispatch BEFORE importing core.app so the web stack never loads here.
        from controller.__main__ import main as controller_main
        return controller_main(argv[1:])
    if argv and argv[0] == "--debug-server":
        # Flight recorder - separate process by design (it must outlive a broken core). Same
        # dispatch-before-core rule: the web app never loads here.
        from debug_server.entry import main as debug_main
        debug_main()
        return None
    if argv and argv[0] == "--debug-export":
        # Offline diagnostics bundle for an air-gapped bench: `run.exe --debug-export [out.zip]`.
        from debug_server.export import main as export_main
        return export_main(argv[1:])
    if argv and argv[0] == "--check-db-drivers":
        # Release gate (deploy/verify-build.ps1): import every report/MES database driver the way
        # SQLAlchemy does, INSIDE the built exe. mssql+pyodbc imports pyodbc dynamically, which
        # PyInstaller cannot see - a build without it looks fine until "driver not installed" in the
        # field. Prints one JSON line per provider; exit 1 if any cannot be imported.
        import json

        from core.services import dbconn
        results = [dbconn.check_dbapi(p) for p in dbconn.PROVIDERS]
        for r in results:
            print(json.dumps(r))
        return 0 if all(r["ok"] for r in results) else 1
    from core.app import app
    from core.serve import serve
    # TMF_PORT: private port for the release gate (deploy/verify-build.ps1) so it can boot the built exe
    # while a real station already answers :8000.
    serve(app, host="127.0.0.1", port=int(os.environ.get("TMF_PORT") or 8000))   # explicit selector loop: see core/serve.py
    return None


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main() or 0)

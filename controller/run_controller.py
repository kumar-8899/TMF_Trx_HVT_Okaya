"""Frozen controller entry point — a plain SCRIPT, mirroring `backend/run.py`.

`build_release.py` Nuitka-compiles THIS (not `controller/__main__.py`). Pointing Nuitka at a
package's `__main__.py` makes it skip the pure-Python stdlib (encodings, threading, asyncio pure
parts), so the frozen `controller.exe` crashes at startup with
`Fatal Python error: Failed to import encodings module` / `No module named 'threading'` before it
ever reaches `main()`. Compiling a top-level script (like the backend does) bundles the full stdlib
on every Nuitka backend (MSVC, MinGW, zig). Behaviour is identical to `python -m controller
[config.json]` — argv is passed straight through to `controller.__main__.main()`.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import sys

from controller.__main__ import main

if __name__ == "__main__":
    # aiomqtt (paho) needs a selector loop; Windows defaults to Proactor (mirrors run.py).
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    multiprocessing.freeze_support()
    raise SystemExit(main())

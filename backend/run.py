"""PyInstaller sidecar entry point. Serves the FastAPI app via uvicorn.

The app object is imported directly (not by string) so PyInstaller bundles the
`core` package. Business modules are discovered dynamically at runtime, so they
are pulled in by tmf-sidecar.spec (collect_submodules + bundled manifest/schema
JSON), not by static analysis here.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import sys

import uvicorn

from core.app import app


def main() -> None:
    # aiomqtt (paho) needs a selector loop; Windows defaults to Proactor.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info", loop="asyncio")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

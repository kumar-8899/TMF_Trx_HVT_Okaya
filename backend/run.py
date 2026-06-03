"""PyInstaller sidecar entry point. Serves the FastAPI app via uvicorn."""

from __future__ import annotations

import asyncio
import sys

import uvicorn


def main() -> None:
    # aiomqtt (paho) needs a selector loop; Windows defaults to Proactor, which
    # does not implement socket add_reader/remove_writer. Force selector first.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("core.app:app", host="127.0.0.1", port=8000, log_level="info", loop="asyncio")


if __name__ == "__main__":
    main()

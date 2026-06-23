"""Debug Server entrypoint (DEBUG_SERVER.md §2). Standalone dev sidecar.

    python run_debug_server.py            # broker 127.0.0.1:1883, UI on :8001
    TMF_DEBUG_NO_AUTH=1 python run_debug_server.py   # skip token check (dev only)

Connects to the station's loopback broker, captures the low-rate topic set, and
serves its own REST + WS + UI on its own port. Never a dependency of the core.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

import uvicorn

from debug_server.app import build_app
from debug_server.auth import TokenChecker
from debug_server.config import DebugConfig
from debug_server.ingest import Ingestor
from debug_server.subscriber import run_subscriber


def main() -> None:
    if sys.platform == "win32":   # aiomqtt/paho need a selector loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    config = DebugConfig.from_env()
    ingestor = Ingestor(config.station, capacity=config.ring_capacity,
                        orphan_timeout_s=config.orphan_timeout_s)
    checker = TokenChecker(config.core_url, require_auth=config.require_auth)
    app = build_app(ingestor, config, checker)

    @app.on_event("startup")
    async def _start() -> None:
        app.state._sub = asyncio.create_task(run_subscriber(ingestor, config))

    @app.on_event("shutdown")
    async def _stop() -> None:
        task = getattr(app.state, "_sub", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    print(f"Debug Server: broker {config.broker_host}:{config.broker_port} "
          f"station={config.station} → http://127.0.0.1:{config.port}  "
          f"(auth={'on' if config.require_auth else 'OFF'})")
    uvicorn.run(app, host="127.0.0.1", port=config.port, log_level="info", loop="asyncio")


if __name__ == "__main__":
    main()

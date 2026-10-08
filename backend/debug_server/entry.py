"""Debug Server entrypoint (DEBUG_SERVER.md §2). Standalone sidecar.

Connects to the station's loopback broker, captures the low-rate topic set, and
serves its own REST + WS + UI on its own port. Never a dependency of the core.

Reached two ways: `python run_debug_server.py` (source) and `run.exe --debug-server` (an installed,
frozen build - the flight recorder is most needed exactly there, FRAMEWORK CR A2).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

from core.paths import state_root
from core.serve import serve
from debug_server.app import build_app
from debug_server.auth import TokenChecker
from debug_server.config import DebugConfig, _load_app_json
from debug_server.ingest import Ingestor
from debug_server.logdiscipline import LogDiscipline, load_variable_meta
from debug_server.rollingsink import RollingSink
from debug_server.snapshot import SnapshotBuffer
from debug_server.subscriber import run_subscriber


def main() -> None:
    if sys.platform == "win32":   # aiomqtt/paho need a selector loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    config = DebugConfig.from_env()
    try:
        config.validate()   # refuse 0.0.0.0 / an unauthenticated remote surface (§3.1/§3.2)
    except ValueError as exc:
        print(f"Debug Server: refusing to start — {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    directory = Path(config.rolling.dir)
    if not directory.is_absolute():
        directory = state_root() / directory   # data/debug lives with the state, not the swappable run.dist
    rolling = RollingSink(config.rolling, directory, queue_size=config.limits.queue_size) \
        if config.rolling.enabled else None
    snapshot = SnapshotBuffer(config.snapshot, directory) if config.snapshot.enabled else None
    ingestor = Ingestor(config.station, capacity=config.ring_capacity,
                        orphan_timeout_s=config.orphan_timeout_s, rolling=rolling, snapshot=snapshot)
    if rolling is not None:
        # Discipline gates what reaches disk (§4): value/# → deadband/summary/edges,
        # everything else → repeat-collapse + rate-limit. The raw ring is untouched.
        var_meta = load_variable_meta(_load_app_json())
        ingestor.discipline = LogDiscipline(config.analog, config.digital, config.limits,
                                            var_meta, rolling.enqueue)
    checker = TokenChecker(config.core_url, require_auth=config.require_auth,
                           static_token=config.token)
    app = build_app(ingestor, config, checker)

    @app.on_event("startup")
    async def _start() -> None:
        if rolling is not None:
            rolling.start()
        app.state._sub = asyncio.create_task(run_subscriber(ingestor, config))

    @app.on_event("shutdown")
    async def _stop() -> None:
        task = getattr(app.state, "_sub", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if snapshot is not None:
            snapshot.flush_due()
        if rolling is not None:
            rolling.stop()

    reach = "loopback" if config.is_loopback() else f"REMOTE {config.bind_host}"
    print(f"Debug Server: broker {config.broker_host}:{config.broker_port} "
          f"station={config.station} -> http://{config.bind_host}:{config.port}  "
          f"({reach}, auth={'on' if config.require_auth else 'OFF'})")
    serve(app, host=config.bind_host, port=config.port)   # explicit selector loop: see core/serve.py


if __name__ == "__main__":
    main()

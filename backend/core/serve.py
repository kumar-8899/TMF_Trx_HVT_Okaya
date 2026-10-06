"""Run an ASGI app under uvicorn on an explicit selector event loop, and exit cleanly.

aiomqtt (paho) registers sockets with `loop.add_reader`, which only a selector loop supports.
On Windows the default loop is Proactor. Setting `WindowsSelectorEventLoopPolicy` is NOT enough
any more: uvicorn (observed with 0.54; a fresh install resolves it, the older 0.34 did not do
this) builds its own loop through a loop factory and returns a `ProactorEventLoop` on Windows,
ignoring the policy. The MQTT bridge then fails on every connect with
`NotImplementedError` from `add_reader` and the station stays offline.

So we do not let uvicorn choose: `loop="none"` stops uvicorn touching the loop, and the
`asyncio.Runner` (Python 3.11+, our floor) is given the selector loop explicitly.

Shutdown. uvicorn waits, with no limit by default, for every open connection (a browser tab with a
live WebSocket) before it runs the app's lifespan shutdown. The lifespan shutdown is where the
supervised controller is stopped, so a tab left open made **Exit station** stall until the
`/system/shutdown` watchdog hard-exited the backend and left the controller running on its own
(no instruments safe-stated, still answering on MQTT). `timeout_graceful_shutdown` bounds that wait
so the lifespan shutdown always runs, and `force_exit` makes the watchdog stop the controller first.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any, Callable

GRACEFUL_SHUTDOWN_TIMEOUT_S = 5


def serve(app: Any, *, host: str, port: int, log_level: str = "info",
          timeout_graceful_shutdown: int | None = GRACEFUL_SHUTDOWN_TIMEOUT_S) -> None:
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=port, log_level=log_level, loop="none",
        timeout_graceful_shutdown=timeout_graceful_shutdown))
    # After a graceful stop uvicorn re-raises the signal that asked for it (so Ctrl-C still ends a
    # bare process); the server has already shut down cleanly by then, so that is not an error.
    with contextlib.suppress(KeyboardInterrupt), asyncio.Runner(
            loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(server.serve())


def force_exit(app: Any, code: int = 0, *, exit_fn: Callable[[int], Any] = os._exit) -> None:
    """Hard-exit the process, but stop the supervised controller FIRST.

    `os._exit` skips the lifespan teardown, so a hard exit on its own orphans the controller child.
    This is the watchdog for a shutdown that stalled: take the controller (and its whole process
    tree) down, then exit."""
    sup = getattr(getattr(app, "state", None), "controller", None)
    if sup is not None:
        with contextlib.suppress(Exception):
            sup.stop()
    exit_fn(code)

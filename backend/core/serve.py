"""Run an ASGI app under uvicorn on an explicit selector event loop.

aiomqtt (paho) registers sockets with `loop.add_reader`, which only a selector loop supports.
On Windows the default loop is Proactor. Setting `WindowsSelectorEventLoopPolicy` is NOT enough
any more: uvicorn (observed with 0.54; a fresh install resolves it, the older 0.34 did not do
this) builds its own loop through a loop factory and returns a `ProactorEventLoop` on Windows,
ignoring the policy. The MQTT bridge then fails on every connect with
`NotImplementedError` from `add_reader` and the station stays offline.

So we do not let uvicorn choose: `loop="none"` stops uvicorn touching the loop, and the
`asyncio.Runner` (Python 3.11+, our floor) is given the selector loop explicitly.
"""

from __future__ import annotations

import asyncio
from typing import Any


def serve(app: Any, *, host: str, port: int, log_level: str = "info") -> None:
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level=log_level, loop="none"))
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(server.serve())

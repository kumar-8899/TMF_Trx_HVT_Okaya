"""core.serve.serve runs uvicorn on a SELECTOR loop (aiomqtt needs add_reader).

Regression: uvicorn >= 0.35 builds its own loop through a loop factory and returns a
ProactorEventLoop on Windows, ignoring set_event_loop_policy, so the MQTT bridge failed with
NotImplementedError from add_reader on a fresh install (uvicorn 0.54).
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket

from core.serve import serve


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_runs_on_a_selector_loop():
    seen: dict[str, object] = {}

    async def app(scope, receive, send):
        if scope["type"] != "lifespan":
            return
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                loop = asyncio.get_running_loop()
                seen["loop"] = type(loop).__name__
                probe = socket.socket()
                try:                                  # the exact call aiomqtt/paho makes
                    loop.add_reader(probe.fileno(), lambda: None)
                    loop.remove_reader(probe.fileno())
                    seen["add_reader"] = True
                except NotImplementedError:
                    seen["add_reader"] = False
                finally:
                    probe.close()
                await send({"type": "lifespan.startup.complete"})
                signal.raise_signal(signal.SIGINT)    # uvicorn's graceful-exit handler
            elif msg["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    # uvicorn re-raises the captured SIGINT after its graceful shutdown (so Ctrl-C still ends a
    # real process); in a test that surfaces as KeyboardInterrupt once the server has stopped.
    with contextlib.suppress(KeyboardInterrupt):
        serve(app, host="127.0.0.1", port=_free_port(), log_level="warning")

    assert seen["add_reader"] is True, f"loop {seen['loop']} cannot add_reader"
    assert "Selector" in str(seen["loop"])

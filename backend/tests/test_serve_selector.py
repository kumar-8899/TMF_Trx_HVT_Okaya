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
import threading
import time
import types

from core.serve import force_exit, serve


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


def test_serve_shuts_down_while_a_connection_is_still_open():
    """Regression: a browser tab left open (a live WebSocket / streaming response) made uvicorn wait
    forever for the connection before running the lifespan shutdown, which is where the supervised
    controller is stopped. 'Exit station' then stalled until the watchdog hard-exited the backend
    and left the controller running on its own. The graceful-shutdown timeout bounds the wait."""
    seen: dict[str, object] = {"shutdown": False}
    port = _free_port()
    started = time.monotonic()

    async def app(scope, receive, send):
        if scope["type"] == "http":                       # a response that never finishes
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"x", "more_body": True})
            await asyncio.Event().wait()
            return
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
                seen["client"] = asyncio.create_task(_hold_open_then_interrupt(port))
            elif msg["type"] == "lifespan.shutdown":
                seen["shutdown"] = True
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _hold_open_then_interrupt(p: int) -> None:
        for _ in range(50):                               # wait for the listener to come up
            try:
                _reader, writer = await asyncio.open_connection("127.0.0.1", p)
                break
            except OSError:
                await asyncio.sleep(0.1)
        writer.write(b"GET /hang HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        await asyncio.sleep(0.5)                          # the request is now in flight
        signal.raise_signal(signal.SIGINT)                # ask for the graceful exit

    # Safety net so a regression fails the test instead of hanging it: a SECOND SIGINT makes uvicorn
    # force-exit, which skips the lifespan shutdown and so fails the assertion below.
    guard = threading.Timer(12.0, lambda: signal.raise_signal(signal.SIGINT))
    guard.daemon = True
    guard.start()
    try:
        serve(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1)
    finally:
        guard.cancel()

    assert seen["shutdown"] is True, "lifespan shutdown never ran: the open connection blocked it"
    assert time.monotonic() - started < 10


def test_force_exit_stops_the_controller_before_exiting():
    order: list[str] = []

    class _Sup:
        def stop(self):
            order.append("controller.stop")

    class _App:
        state = types.SimpleNamespace(controller=_Sup())

    force_exit(_App(), 0, exit_fn=lambda code: order.append(f"exit({code})"))
    assert order == ["controller.stop", "exit(0)"]


def test_force_exit_still_exits_when_the_controller_stop_fails_or_there_is_none():
    class _Boom:
        def stop(self):
            raise RuntimeError("stuck")

    codes: list[int] = []
    force_exit(types.SimpleNamespace(state=types.SimpleNamespace(controller=_Boom())), 0, exit_fn=codes.append)
    force_exit(types.SimpleNamespace(state=types.SimpleNamespace()), 3, exit_fn=codes.append)
    assert codes == [0, 3]

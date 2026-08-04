"""One asyncio loop on its own thread for all instrument I/O.

instrumentlib is async (InstrumentBase.invoke is a coroutine) but the controller runs
station work on OS threads (PYTHON_CONTROLLER.md §2.2). A single background loop owns the
instrument registry; station threads and MQTT callbacks submit coroutines to it and block
for the result. The per-instance lock in InstrumentBase then arbitrates shared instruments
in-process (§2.1) with no cross-thread races."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Coroutine


class AsyncLoopThread:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="instrument-loop", daemon=True)
        self._ready = threading.Event()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(5.0)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def run(self, coro: Coroutine, *, timeout: float | None = None) -> Any:
        """Submit a coroutine and block for its result (called from a worker thread)."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)

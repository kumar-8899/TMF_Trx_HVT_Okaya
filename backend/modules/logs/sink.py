"""LogsDiagSink — the single error_log write path with dedup (LOGS.md §6).

Diagnostics sinks are called synchronously, but the DB write is async, so
`receive()` is sync and only enqueues; one consumer task drains the queue and
does filter -> dedup -> write. Both callers (in-process Python diag, MQTT LabVIEW
diag) feed this one queue, so dedup state lives in one place and double-write is
structurally impossible.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

from modules.logs.contract import LEVEL_ORDER

# repo.put-shaped callable: (record_type, data, *, summary) -> id
PutFn = Callable[..., Awaitable[str]]

_ERROR_KEYS = ("seq", "level", "subsystem", "message", "context", "exception")


class LogsDiagSink:
    def __init__(
        self,
        put: PutFn,
        *,
        min_level: str = "warning",
        subsystems: tuple[str, ...] = (),
        dedup_enabled: bool = True,
        window_s: float = 10.0,
    ) -> None:
        self._put = put
        self._min_level = LEVEL_ORDER.index(min_level) if min_level in LEVEL_ORDER else 0
        self._subsystems = set(subsystems)
        self._dedup = dedup_enabled
        self._window_s = window_s
        self._queue: asyncio.Queue = asyncio.Queue()
        self._windows: dict[tuple, dict] = {}
        self._task: asyncio.Task | None = None

    # --- ingress (sync, non-blocking) --------------------------------------

    def receive(self, event: dict, source: str | None = None) -> None:
        ev = dict(event)
        ev["source"] = ev.get("source") or source or "python"
        self._queue.put_nowait(ev)

    # --- consumer lifecycle ------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="logs-sink")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        await self.flush_all()

    async def _run(self) -> None:
        tick = max(0.5, self._window_s / 4)
        while True:
            try:
                ev = await asyncio.wait_for(self._queue.get(), timeout=tick)
            except asyncio.TimeoutError:
                await self.flush_expired()
                continue
            except asyncio.CancelledError:
                break
            await self.handle(ev)
            await self.flush_expired()

    # --- core logic (directly unit-testable) -------------------------------

    def _passes_filter(self, ev: dict) -> bool:
        if LEVEL_ORDER.index(ev.get("level", "info")) < self._min_level:
            return False
        if self._subsystems and ev.get("subsystem") not in self._subsystems:
            return False
        return True

    async def handle(self, ev: dict) -> None:
        if not self._passes_filter(ev):
            return
        if not self._dedup:
            await self._write(ev, repeat_count=1, coalesced=False)
            return
        sig = (ev.get("source"), ev.get("level"), ev.get("subsystem"), ev.get("message"))
        now = float(ev.get("ts") or time.time())
        win = self._windows.get(sig)
        if win is None:
            await self._write(ev, repeat_count=1, coalesced=False)  # first is always durable
            self._windows[sig] = {"count": 1, "window_start": now, "last_ts": now, "sample": ev}
        else:
            win["count"] += 1
            win["last_ts"] = now

    async def flush_expired(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        for sig, win in list(self._windows.items()):
            if now - win["window_start"] >= self._window_s:
                await self._close(sig, win)

    async def flush_all(self) -> None:
        for sig, win in list(self._windows.items()):
            await self._close(sig, win)

    async def _close(self, sig: tuple, win: dict) -> None:
        if win["count"] > 1:
            await self._write(
                win["sample"], repeat_count=win["count"], coalesced=True,
                window_start=win["window_start"], window_end=win["last_ts"],
            )
        self._windows.pop(sig, None)

    async def _write(
        self, ev: dict, *, repeat_count: int, coalesced: bool,
        window_start: float | None = None, window_end: float | None = None,
    ) -> str:
        data = {k: ev.get(k) for k in _ERROR_KEYS}
        data["source"] = ev.get("source", "python")
        data.setdefault("context", {})
        data["repeat_count"] = repeat_count
        data["coalesced"] = coalesced
        data["window_start"] = window_start
        data["window_end"] = window_end
        summary = f"[{data.get('level')}] {data.get('subsystem')}: {data.get('message')}"
        return await self._put("error_log", data, summary=summary)

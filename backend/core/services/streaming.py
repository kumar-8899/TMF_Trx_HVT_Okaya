"""StreamHub — asyncio fan-out for WebSocket relays (CORE.md §1 web edge).

One producer (a bridge subscription handler) calls broadcast(); N WebSocket
clients each hold a bounded queue and drain it. Bounded + latest-wins: a slow
client drops the oldest frame rather than back-pressuring the producer
(LABVIEW_BRIDGE.md §6 — loss under load is expected and correct for streams).

Snapshot-on-join is the caller's job: send bridge.latest(topic) before draining
(streams have a cached latest; events do not).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator


class StreamHub:
    def __init__(self, maxsize: int = 64) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._maxsize = maxsize

    @property
    def count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def broadcast(self, payload: dict) -> None:
        for q in self._subscribers:
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()  # drop oldest — latest-wins
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(payload)

    @contextlib.asynccontextmanager
    async def subscription(self) -> AsyncIterator[asyncio.Queue]:
        """Scoped subscribe/unsubscribe for a WS handler."""
        q = self.subscribe()
        try:
            yield q
        finally:
            self.unsubscribe(q)

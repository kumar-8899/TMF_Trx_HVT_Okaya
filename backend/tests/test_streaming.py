"""StreamHub fan-out (CORE.md §1 web edge)."""

import asyncio

from core.services.streaming import StreamHub


async def test_broadcast_reaches_all_subscribers():
    hub = StreamHub()
    a = hub.subscribe()
    b = hub.subscribe()
    hub.broadcast({"seq": 1})
    assert await a.get() == {"seq": 1}
    assert await b.get() == {"seq": 1}
    assert hub.count == 2


async def test_unsubscribe_stops_delivery():
    hub = StreamHub()
    q = hub.subscribe()
    hub.unsubscribe(q)
    hub.broadcast({"seq": 1})
    assert hub.count == 0
    assert q.empty()


async def test_latest_wins_drops_oldest_when_full():
    hub = StreamHub(maxsize=2)
    q = hub.subscribe()
    for seq in (1, 2, 3):
        hub.broadcast({"seq": seq})
    # maxsize 2 -> oldest (1) dropped, newest two kept
    assert await q.get() == {"seq": 2}
    assert await q.get() == {"seq": 3}
    assert q.empty()


async def test_subscription_context_manager():
    hub = StreamHub()
    async with hub.subscription() as q:
        assert hub.count == 1
        hub.broadcast({"x": 1})
        assert await asyncio.wait_for(q.get(), 1) == {"x": 1}
    assert hub.count == 0

"""debug_tool.live - all-station subscription set and the reconnecting ingest loop (fake MQTT client)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from debug_server.ingest import Ingestor
from debug_tool import live


def test_subscriptions_use_a_station_wildcard_and_never_stream():
    subs = live.subscriptions()
    assert all(s.startswith("tmf/+/") for s in subs)
    assert not any("stream" in s for s in subs)
    assert "tmf/+/diag" in subs and "tmf/+/event/#" in subs


def test_station_of_topic():
    assert live.station_of("tmf/st2/diag") == "st2"
    assert live.station_of("other/x/y") == "" and live.station_of("tmf") == ""


def test_parse_any_station_takes_the_station_from_the_topic():
    r = live.parse_any_station("tmf/st3/diag", json.dumps({"ts": 1.0, "level": "info", "subsystem": "x", "message": "m"}))
    assert r.station == "st3"


class FakeClient:
    def __init__(self, messages, fail_after=False):
        self.subscribed, self._messages, self._fail = [], messages, fail_after
        self.messages = self._gen()

    async def _gen(self):
        for topic, payload in self._messages:
            yield SimpleNamespace(topic=SimpleNamespace(value=topic), payload=payload)
        if self._fail:
            raise ConnectionError("broker went away")
        await asyncio.sleep(3600)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)


def diag(msg):
    return json.dumps({"ts": 1.0, "level": "info", "subsystem": "x", "message": msg}).encode()


@pytest.mark.asyncio
async def test_ingests_every_station_and_reports_connected():
    ing = Ingestor("*", capacity=100)
    states = []
    client = FakeClient([("tmf/st1/diag", diag("a")), ("tmf/st2/diag", diag("b"))])
    task = asyncio.create_task(live.run_all_stations(ing, "h", 1, on_state=states.append, client_factory=lambda: client))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert states[0] is True and ing.broker_connected is True
    assert {r.station for r in ing.ring.all()} == {"st1", "st2"}
    assert client.subscribed == live.subscriptions()


@pytest.mark.asyncio
async def test_reconnects_after_the_broker_drops(monkeypatch):
    monkeypatch.setattr(live.asyncio, "sleep", asyncio.sleep)       # keep the real sleep; the loop waits 1 s before retrying
    ing = Ingestor("*", capacity=100)
    states = []
    clients = iter([FakeClient([("tmf/st1/diag", diag("first"))], fail_after=True), FakeClient([("tmf/st1/diag", diag("second"))])])
    task = asyncio.create_task(live.run_all_stations(ing, "h", 1, on_state=states.append, client_factory=lambda: next(clients)))
    await asyncio.sleep(1.6)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert states[:3] == [True, False, True]                        # up, down, up again - and the loop never died

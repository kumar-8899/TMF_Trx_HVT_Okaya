"""Live MQTT feed for the Debug Tool: ALL stations, never `stream/#`.

`debug_server.subscriber.run_subscriber` follows ONE station (`config.station`). A PC can run N sockets
(MULTI_STATION.md), and the tool must see all of them, so this subscribes with a `+` station wildcard and derives the
station from each topic. Records go through the same `parse` -> `Ingestor.ingest` pipeline as the in-app sidecar, so
the ring, liveness, request pairing and (in own-recorder mode) the rolling sink/snapshots behave identically.
"""

from __future__ import annotations

import asyncio

from debug_server.capture import parse

# Same low-rate capture set as the in-app sidecar (debug_server/subscriber.py); stream/# is excluded on purpose.
CAPTURE = ("event/#", "diag", "diag/#", "value/#", "status", "cmd/#")


def subscriptions() -> list[str]:
    return [f"tmf/+/{t}" for t in CAPTURE]


def station_of(topic: str) -> str:
    parts = topic.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "tmf" else ""


def parse_any_station(topic: str, raw: bytes | str):
    return parse(topic, station_of(topic), raw)


async def run_all_stations(ingestor, host: str, port: int, *, on_state=None, client_factory=None) -> None:
    """Connect, subscribe, ingest forever; reconnect after any failure. `on_state(connected: bool)` tells the engine
    (so `bench_health` can say the live source is down). `client_factory` is for tests."""
    if client_factory is None:
        import aiomqtt

        def client_factory():                                     # noqa: ANN202
            return aiomqtt.Client(hostname=host, port=port, identifier="tmf-debug-tool")
    while True:
        try:
            async with client_factory() as client:
                ingestor.broker_connected = True
                if on_state:
                    on_state(True)
                for s in subscriptions():
                    await client.subscribe(s, qos=1)
                async for msg in client.messages:
                    ingestor.ingest(parse_any_station(msg.topic.value, msg.payload))
        except asyncio.CancelledError:
            raise
        except Exception:                                         # noqa: BLE001 - a debug tool never dies; it reconnects
            ingestor.broker_connected = False
            if on_state:
                on_state(False)
            await asyncio.sleep(1.0)

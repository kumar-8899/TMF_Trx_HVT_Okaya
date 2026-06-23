"""MQTT subscriber (DEBUG_SERVER.md §3). Captures the low-rate topic set into the
ingestor. stream/# is deliberately never subscribed (§0)."""

from __future__ import annotations

import asyncio

import aiomqtt

from debug_server.capture import parse
from debug_server.config import DebugConfig
from debug_server.ingest import Ingestor

# Capture set (§0), scoped to the station. NOTE: cmd/# carries both requests
# (cmd/<op>) and replies (cmd/resp/<client>); stream/# is excluded on purpose.
_CAPTURE = ("event/#", "diag", "diag/#", "value/#", "status", "cmd/#")


async def run_subscriber(ingestor: Ingestor, config: DebugConfig) -> None:
    station = config.station
    subs = [f"tmf/{station}/{t}" for t in _CAPTURE]
    while True:
        try:
            async with aiomqtt.Client(hostname=config.broker_host, port=config.broker_port,
                                      identifier=f"tmf-debug-{station}") as client:
                ingestor.broker_connected = True
                for s in subs:
                    await client.subscribe(s, qos=1)
                async for msg in client.messages:
                    ingestor.ingest(parse(msg.topic.value, station, msg.payload))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — bench tool: never die, just reconnect
            ingestor.broker_connected = False
            await asyncio.sleep(1.0)

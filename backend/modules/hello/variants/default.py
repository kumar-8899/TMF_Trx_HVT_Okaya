"""The hello `default` variant (CORE.md §9).

Proves the whole path: a route that round-trips through MQTT to the LabVIEW stub
and emits one diagnostic. init/start/stop are the two-phase bring-up; nothing
moves traffic until start.
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.hello.api import build_router


class HelloDefault:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.router = build_router(self)
        self.mqtt_handlers: list = []

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "HelloDefault":
        return cls(core, config)

    async def init(self) -> None:
        # Wire up only — no traffic yet (CORE.md §2.2).
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        online = bool(self.core.bridge and self.core.bridge.online)
        return Health(
            status=HealthStatus.OK if online else HealthStatus.DEGRADED,
            detail="bridge online" if online else "bridge link not online",
        )

    async def ping(self) -> dict:
        reply = await self.core.bridge.request("hello.echo", {"from": "hello", "station": self.core.station})
        self.core.diag.info("hello", "pinged", station=self.core.station)
        return {"pong": True, "station": self.core.station, "echo": reply}

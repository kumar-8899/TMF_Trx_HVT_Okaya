"""Logs `db` variant (LOGS.md §12).

L1: lifecycle skeleton + config parse. The sink + dedup (L2), queries +
record_action (L3), REST (L4), and pruning + run-event subscriber (L5) land in
later sub-phases.
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus


class DbLogs:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.station = core.station
        self.router = None  # built in L4
        self.mqtt_handlers: list = []  # wired in L2/L5

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DbLogs":
        return cls(core, config)

    async def init(self) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK, detail="logs db variant")

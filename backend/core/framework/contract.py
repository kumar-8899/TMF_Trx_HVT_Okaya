"""Module contract surface + the injected service container (CORE.md §1, §2.2).

`Core` holds the real services; `Core.select(deps)` hands a module exactly the
services its manifest declared (CORE.md §4) — explicit DI, no framework.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

# --- health ---------------------------------------------------------------


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class Health:
    status: HealthStatus = HealthStatus.OK
    detail: str | None = None


# --- the module contract (CORE.md §2.2) -----------------------------------


@runtime_checkable
class Module(Protocol):
    router: Any | None
    mqtt_handlers: list[tuple[str, Callable]]

    @classmethod
    def construct(cls, core: "CoreServices", config: dict) -> "Module": ...
    async def init(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> Health: ...


# --- injected container ----------------------------------------------------

# Names a module may list in manifest.core_dependencies -> CoreServices field.
SERVICE_ALIASES = {
    "db": "db",
    "bridge": "bridge",
    "config": "config",
    "auth": "auth",
    "diag": "diag",
    "diagnostics": "diag",
    "web": "web",
    "interlock": "interlock",
    "licensing": "licensing",
}


@dataclass
class CoreServices:
    """The subset of services a single module declared. Unrequested ones stay None."""

    db: Any = None
    bridge: Any = None
    config: Any = None
    auth: Any = None
    diag: Any = None
    web: Any = None
    interlock: Any = None
    licensing: Any = None    # licensing provider (stub | keystation): session() + load_and_verify()
    station: str = ""
    get_contract: Callable[[str], Any] | None = None


class Core:
    """Holds every real service; `select` projects the per-module subset."""

    def __init__(
        self,
        *,
        db: Any = None,
        bridge: Any = None,
        config: Any = None,
        auth: Any = None,
        diag: Any = None,
        web: Any = None,
        interlock: Any = None,
        licensing: Any = None,
        station: str = "",
    ) -> None:
        self.db = db
        self.bridge = bridge
        self.config = config
        self.auth = auth
        self.diag = diag
        self.web = web
        self.interlock = interlock
        self.licensing = licensing
        self.station = station
        self.contracts: dict[str, Any] = {}  # active module_id -> instance (CORE.md §6.3)

    def get_contract(self, name: str) -> Any:
        if name not in self.contracts:
            raise KeyError(f"no active contract '{name}'")
        return self.contracts[name]

    def select(self, deps: list[str]) -> CoreServices:
        services = CoreServices(station=self.station, get_contract=self.get_contract)
        for dep in deps:
            field_name = SERVICE_ALIASES.get(dep)
            if field_name is None:
                raise KeyError(f"unknown core dependency '{dep}'")
            setattr(services, field_name, getattr(self, field_name))
        return services

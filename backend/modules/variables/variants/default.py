"""variables `default` variant — the variable engine wired into the app.

Builds instrument instances from config (via the instrumentlib registry), exposes the
scalar `variable.*` verbs to LabVIEW over the bridge (Py-served `query/{op}`,
LABVIEW_BRIDGE §5), and a REST surface for the maintenance/human path. Non-scalar
capabilities are NOT here — they go through `capability.request` (§2.2, arriving IL4).
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.variables.api import build_router
from modules.variables.engine import VariableEngine
from modules.variables.instances import InstanceRegistry


class DefaultVariables:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.instances = InstanceRegistry(core.diag)
        self.instances.build(config.get("instances", []), on_command=self._on_cmd)
        self.engine = VariableEngine(self.instances, config.get("variables", {}), core.diag)
        self.router = build_router(self)
        self.mqtt_handlers: list = []

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultVariables":
        return cls(core, config)

    def _on_cmd(self, rec: dict) -> None:
        # every instrument command auto-emits to the diag bus (zero per-library effort)
        msg = rec.get("method") or rec.get("state") or "event"
        ctx = {k: v for k, v in rec.items() if k != "kind" and v is not None}
        self.core.diag.info("instrument", msg, **ctx)

    async def init(self) -> None:
        pass

    async def start(self) -> None:
        await self.instances.connect_all()
        b = self.core.bridge
        if b is not None:
            # LabVIEW commands Python-owned scalar signals through the variable engine.
            b.serve("variable.read", lambda a: self.engine.read(a["name"]))
            b.serve("variable.write", lambda a: self.engine.write(a["name"], a["value"]))
            b.serve("variable.read_many", lambda a: self.engine.read_many(a.get("names", [])))
            b.serve("variable.write_many", lambda a: self.engine.write_many(a.get("values", {})))

    async def stop(self) -> None:
        await self.instances.disconnect_all()

    async def health(self) -> Health:
        unbound = self.engine.unbound()
        n = len(self.instances.all())
        if unbound:
            return Health(status=HealthStatus.DEGRADED,
                          detail=f"{n} instances · unbound variables: {', '.join(unbound)}")
        return Health(status=HealthStatus.OK, detail=f"{n} instances · {len(self.engine.vars)} variables")

    # readiness: unbound variable names block /readyz, loudly (§5.3)
    async def ready(self) -> bool:
        return not self.engine.unbound()

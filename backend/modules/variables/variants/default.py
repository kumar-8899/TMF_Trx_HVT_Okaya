"""variables `default` variant — the variable engine wired into the app.

Builds instrument instances from config (via the instrumentlib registry), exposes the
scalar `variable.*` verbs to LabVIEW over the bridge (Py-served `query/{op}`,
LABVIEW_BRIDGE §5), and a REST surface for the maintenance/human path. Non-scalar
capabilities are NOT here — they go through `capability.request` (§2.2, arriving IL4).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from core.framework.contract import CoreServices, Health, HealthStatus
from instrumentlib.registry import build_index
from modules.variables.api import build_router
from modules.variables.engine import VariableEngine
from modules.variables.instances import InstanceRegistry


class DefaultVariables:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self._load_libraries()          # fills the instrumentlib registry BEFORE building instances
        self.instances = InstanceRegistry(core.diag)
        # Instances are built in start() — they come from the config module's
        # owner=python instruments (single source of truth) merged with any declared
        # inline here; the config module must be constructed first.
        self.engine = VariableEngine(self.instances, config.get("variables", {}), core.diag)
        self.router = build_router(self)
        self.mqtt_handlers: list = []

    def _load_libraries(self) -> None:
        """Import the external instrument-library package(s) so their registration
        decorators fire (INSTRUMENT_LIBRARY.md §10). `library_paths` are added to
        sys.path (the sibling library repo); `library_packages` are imported."""
        for p in self.config.get("library_paths", []):
            if Path(p).is_dir() and p not in sys.path:
                sys.path.insert(0, p)
        for pkg in self.config.get("library_packages", []):
            try:
                importlib.import_module(pkg)
                self.core.diag.info("variables", "instrument library loaded", package=pkg)
            except Exception as exc:  # noqa: BLE001 — a bad library must not crash the app
                self.core.diag.error("variables", "instrument library import failed",
                                     package=pkg, error=str(exc))

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
        # Merge instrument instances: inline config first, then the config module's
        # owner=python instruments (deduped by id in the registry).
        configs = list(self.config.get("instances", []))
        get = getattr(self.core, "get_contract", None)
        if get is not None:
            try:
                configs += await get("config").python_instruments()
            except KeyError:
                pass   # config module not loaded — inline instances only
        self.instances.build(configs, on_command=self._on_cmd)
        await self.instances.connect_all()
        b = self.core.bridge
        if b is not None:
            # LabVIEW commands Python-owned scalar signals through the variable engine.
            b.serve("variable.read", lambda a: self.engine.read(a["name"]))
            b.serve("variable.write", lambda a: self.engine.write(a["name"], a["value"]))
            b.serve("variable.read_many", lambda a: self.engine.read_many(a.get("names", [])))
            b.serve("variable.write_many", lambda a: self.engine.write_many(a.get("values", {})))
            # Non-scalar actions bypass the variable engine (§2.2), by instance id.
            b.serve("capability.request", lambda a: self.call(a["instance"], a["method"], a.get("args")))

    async def call(self, instance_id: str, method: str, args=None) -> dict:
        """capability.request seam (§2.3): a non-scalar action on an instance by id."""
        inst = self.instances.require(instance_id)
        result = await inst.invoke(method, *(args or []))
        return {"instance": instance_id, "method": method, "result": result}

    def libraries(self) -> dict:
        return build_index()

    def instance_status(self) -> list[dict]:
        return self.instances.status()

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

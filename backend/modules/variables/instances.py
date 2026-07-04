"""Instance registry (INSTRUMENT_LIBRARY.md §5.2).

Builds InstrumentBase objects from station config via the instrumentlib REGISTRY
(library_id → class). Cloning is standard instantiation: N entries, N objects, each
with its own connection, state, and lock. Rejects a duplicate resolved resource
string at startup (the in-process double-open guard). An instance whose library is
not registered is skipped loudly (the library repo may not be bundled yet).
"""

from __future__ import annotations

import json

from instrumentlib.registry import REGISTRY


class DoubleOpenError(Exception):
    """Two instances resolved to the same physical resource (§5.2)."""


def _resource_key(cfg: dict) -> str:
    return f"{cfg['library']}:{json.dumps(cfg.get('params', {}), sort_keys=True)}"


class InstanceRegistry:
    def __init__(self, diag):
        self.diag = diag
        self._by_id: dict = {}
        self._resources: set[str] = set()
        self.skipped: list[dict] = []      # {id, library, reason}

    def build(self, configs: list[dict], *, on_command=None) -> None:
        for cfg in configs or []:
            iid, lib_id = cfg["id"], cfg["library"]
            entry = REGISTRY.get(lib_id)
            if entry is None:
                self.skipped.append({"id": iid, "library": lib_id, "reason": "library not registered"})
                self.diag.warning("variables", "instance skipped: unknown library",
                                  instance=iid, library=lib_id)
                continue
            resource = _resource_key(cfg)
            if resource in self._resources:
                raise DoubleOpenError(f"instance '{iid}' resolves to an already-open resource: {resource}")
            inst = entry["class"](
                iid, simulated=cfg.get("simulated", True),
                params=cfg.get("params", {}), on_command=on_command,
            )
            self._by_id[iid] = inst
            self._resources.add(resource)

    def has(self, instance_id: str) -> bool:
        return instance_id in self._by_id

    def get(self, instance_id: str):
        return self._by_id.get(instance_id)

    def require(self, instance_id: str):
        inst = self._by_id.get(instance_id)
        if inst is None:
            from modules.variables.engine import VariableError
            raise VariableError(f"instance '{instance_id}' is not loaded", method="resolve")
        return inst

    def all(self) -> list:
        return list(self._by_id.values())

    def status(self) -> list[dict]:
        """Per-instance state for the UI + health (§5.2, §6)."""
        live = [{
            "id": i.instance_id,
            "library": getattr(type(i), "_declaration", {}).get("library_id"),
            "state": i.state, "simulated": i.simulated,
        } for i in self._by_id.values()]
        skipped = [{"id": s["id"], "library": s["library"], "state": "skipped",
                    "reason": s["reason"]} for s in self.skipped]
        return live + skipped

    async def connect_all(self) -> None:
        for inst in self._by_id.values():
            try:
                await inst.connect()
            except Exception as exc:  # noqa: BLE001 — one bad instrument must not block the rest
                self.diag.warning("variables", "instance connect failed",
                                  instance=inst.instance_id, error=str(exc))

    async def disconnect_all(self) -> None:
        for inst in self._by_id.values():
            try:
                await inst.disconnect()
            except Exception:  # noqa: BLE001
                pass

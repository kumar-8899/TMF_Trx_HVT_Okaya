"""Instrument instance registry (INSTRUMENT_LIBRARY.md §5.2, PYTHON_CONTROLLER.md §9.2).

Builds InstrumentBase objects from config via the instrumentlib REGISTRY (library_id ->
class). Shared across stations (one connection per device); the per-instance lock in
InstrumentBase arbitrates concurrent access. Duplicate resolved resources are rejected at
startup (the double-open guard). instrumentlib is a pip package — NOT the framework app."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from instrumentlib.registry import REGISTRY


class RegistryError(Exception):
    """Two instances resolved to the same device, or a config referenced an unknown library."""


def load_libraries(library_paths: list[str], library_packages: list[str], *, log=None) -> None:
    """Add library repos to sys.path and import their packages so the
    @instrument_library decorators fire and populate REGISTRY (§10)."""
    for p in library_paths:
        if Path(p).is_dir() and p not in sys.path:
            sys.path.insert(0, p)
    for pkg in library_packages:
        try:
            importlib.import_module(pkg)
            if log:
                log("info", f"instrument library loaded: {pkg}")
        except Exception as exc:  # noqa: BLE001 — a bad library must not crash the controller
            if log:
                log("error", f"instrument library import failed: {pkg}: {exc}")


def _resource_key(cfg: dict) -> str:
    return f"{cfg['library']}:{json.dumps(cfg.get('params', {}), sort_keys=True)}"


class InstrumentRegistry:
    def __init__(self, loop, *, log=None) -> None:
        self._loop = loop
        self._log = log
        self._by_id: dict = {}
        self._stations_by_id: dict[str, list[str]] = {}   # instance -> sockets it serves
        self._resources: set[str] = set()
        self.skipped: list[dict] = []

    def build(self, instruments: list[dict], *, simulation: bool = False, on_command=None) -> None:
        for cfg in instruments or []:
            iid, lib_id = cfg["id"], cfg["library"]
            if iid in self._by_id:
                continue
            entry = REGISTRY.get(lib_id)
            if entry is None:
                self.skipped.append({"id": iid, "library": lib_id, "reason": "library not registered"})
                if self._log:
                    self._log("warning", f"instance skipped: unknown library {lib_id} (instance {iid})")
                continue
            resource = _resource_key(cfg)
            if resource in self._resources:
                raise RegistryError(f"instance '{iid}' resolves to an already-open resource: {resource}")
            simulated = bool(cfg.get("simulated", simulation))
            inst = entry["class"](iid, simulated=simulated, params=cfg.get("params", {}),
                                  on_command=on_command)
            self._by_id[iid] = inst
            self._stations_by_id[iid] = list(cfg.get("stations") or [])
            self._resources.add(resource)

    def stations_of(self, instance_id: str) -> list[str]:
        return self._stations_by_id.get(instance_id, [])

    def instances_for_station(self, station: str) -> list:
        """Instances serving a socket: those listing it, plus any with no stations
        declared (treated as serving all)."""
        return [i for iid, i in self._by_id.items()
                if station in self._stations_by_id.get(iid, []) or not self._stations_by_id.get(iid)]

    def get(self, instance_id: str):
        return self._by_id.get(instance_id)

    def require(self, instance_id: str):
        inst = self._by_id.get(instance_id)
        if inst is None:
            raise RegistryError(f"instance '{instance_id}' is not loaded")
        return inst

    def all(self) -> list:
        return list(self._by_id.values())

    async def connect_all(self) -> None:
        for inst in self._by_id.values():
            try:
                await inst.connect()
            except Exception as exc:  # noqa: BLE001 — one bad instrument must not block the rest
                if self._log:
                    self._log("warning", f"instance connect failed: {inst.instance_id}: {exc}")

    async def safe_state_all(self) -> None:
        """Drive every instance to its safe state (run teardown, §5.2). Never raises."""
        await self._safe(self._by_id.values())

    async def safe_state_station(self, station: str) -> None:
        """Teardown only the instances THIS socket owns — aborting st1 must not disturb
        st2's instruments (MULTI_STATION.md §4.1)."""
        await self._safe(self.instances_for_station(station))

    @staticmethod
    async def _safe(instances) -> None:
        for inst in instances:
            try:
                await inst.safe_state()
            except Exception:  # noqa: BLE001 — teardown into an unknown/dead link is best-effort
                pass

    async def disconnect_all(self) -> None:
        for inst in self._by_id.values():
            try:
                await inst.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def status(self) -> list[dict]:
        live = [{"id": i.instance_id, "state": i.state, "simulated": i.simulated,
                 "library": getattr(type(i), "_declaration", {}).get("library_id")}
                for i in self._by_id.values()]
        return live + [{"id": s["id"], "state": "skipped", "reason": s["reason"]} for s in self.skipped]

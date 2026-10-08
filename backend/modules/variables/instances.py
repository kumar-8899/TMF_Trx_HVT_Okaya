"""Instance registry (INSTRUMENT_LIBRARY.md §5.2).

Builds InstrumentBase objects from station config via the instrumentlib REGISTRY
(library_id → class). Cloning is standard instantiation: N entries, N objects, each
with its own connection, state, and lock. Rejects a duplicate resolved resource
string at startup (the in-process double-open guard). An instance whose library is
not registered is skipped loudly (the library repo may not be bundled yet).

**Single-client-instrument race fix (framework bug — see PYTHON_CONTROLLER.md):** when
the app runs `controller.kind == "python"`, the SUPERVISED controller subprocess already
builds its own InstrumentRegistry and holds the one live connection to every owner=python
instrument. Building a SECOND, independent connection here — as this registry always did
before — races the controller for single-client hardware (e.g. a VISA `...::SOCKET`
resource) and the loser sticks at DISCONNECTED forever (a failed initial `connect()` never
retries). So `build(..., bridge=...)` puts every instance in *proxy mode* instead: no
transport is ever opened in this process; every `invoke()` reaches the instrument through
the controller's own connection over the bridge (`instrument.call`/`instrument.status`,
mirroring the `variable.*`/`instrument.test` verbs it already serves). Under
`controller.kind == "labview"` there is no controller subprocess to proxy through (and
owner=python instruments are reached only through this layer per INSTRUMENT_LIBRARY.md §0)
so `bridge` stays None and instances connect directly, exactly as before.
"""

from __future__ import annotations

import json

from instrumentlib import errors as instrumentlib_errors
from instrumentlib.errors import InstrumentError, NotConnected
from instrumentlib.registry import REGISTRY


class DoubleOpenError(Exception):
    """Two instances resolved to the same physical resource (§5.2)."""


def _resource_key(cfg: dict) -> str:
    return f"{cfg['library']}:{json.dumps(cfg.get('params', {}), sort_keys=True)}"


class ProxiedInstrument:
    """Stands in for a directly-connected InstrumentBase when the supervised Python
    controller already owns the one live connection to this instrument. Duck-types the
    subset of InstrumentBase's surface the rest of this module needs — `instance_id`,
    `simulated`, `state`, `_declaration`, `connect()`/`disconnect()` (both no-ops — the
    controller owns the connection; this must never open a transport, which is exactly
    the double-open bug it exists to prevent), and `invoke(method, *args)`, which reaches
    the real instrument through the controller's bridge verb `instrument.call` instead of
    a local transport call. `state` starts `"disconnected"` and is corrected by
    `InstanceRegistry.refresh_proxied_status()` (never at connect_all()/boot time; a fresh
    poll on each real status request is more honest than a cached flag that can never
    un-stick itself)."""

    def __init__(self, instance_id: str, *, library: str, capabilities: list[str],
                simulated: bool, bridge, station: str, timeout_s: float = 20.0) -> None:
        self.instance_id = instance_id
        self.simulated = simulated
        self.state = "disconnected"   # corrected by the first status refresh
        self._declaration = {"library_id": library, "capabilities": list(capabilities)}
        self._bridge = bridge
        self._station = station
        self._timeout = timeout_s

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def invoke(self, method: str, *args):
        from core.services.bridge import BridgeError, BridgeTimeout

        try:
            reply = await self._bridge.request(
                "instrument.call",
                {"instance_id": self.instance_id, "method": method, "args": list(args)},
                station=self._station, timeout=self._timeout,
            )
        except BridgeTimeout as exc:
            raise NotConnected(f"{self.instance_id} not reachable via the controller (timeout)",
                               instance_id=self.instance_id, method=method) from exc
        except BridgeError as exc:
            raise NotConnected(f"{self.instance_id} not reachable via the controller: {exc}",
                               instance_id=self.instance_id, method=method) from exc
        if reply.get("ok"):
            return reply.get("result")
        err = reply.get("error") or {}
        code = err.get("code")
        exc_cls = getattr(instrumentlib_errors, code, None) if code else None
        if not (isinstance(exc_cls, type) and issubclass(exc_cls, InstrumentError)):
            exc_cls = InstrumentError
        detail = err.get("detail")
        if err.get("cause"):      # keep the controller-side root cause visible on the rebuilt exception
            detail = f"{detail} | cause: {err['cause']}" if detail else f"cause: {err['cause']}"
        raise exc_cls(err.get("message") or "instrument call failed",
                     instance_id=self.instance_id, method=method,
                     code=code, detail=detail)


class InstanceRegistry:
    def __init__(self, diag):
        self.diag = diag
        self._by_id: dict = {}
        self._resources: set[str] = set()
        self.skipped: list[dict] = []      # {id, library, reason}
        self._bridge = None
        self._station: str = ""

    def build(self, configs: list[dict], *, on_command=None, bridge=None, station: str = "") -> None:
        """`bridge` non-None (only when `controller.kind == "python"`) puts every
        instance in this batch into proxy mode — see module docstring."""
        if bridge is not None:
            self._bridge, self._station = bridge, station
        for cfg in configs or []:
            iid, lib_id = cfg["id"], cfg["library"]
            if iid in self._by_id:
                continue   # already built (inline config wins over the config-module copy)
            entry = REGISTRY.get(lib_id)
            if entry is None:
                self.skipped.append({"id": iid, "library": lib_id, "reason": "library not registered"})
                self.diag.error("variables", "instance skipped: unknown library",
                                instance=iid, library=lib_id)
                continue
            if bridge is not None:
                # Proxy mode: read the library's declared facts (capabilities) straight off
                # the REGISTRY entry — never instantiate the real driver class, so nothing is
                # ever opened here. No resource-key bookkeeping either: nothing local is
                # opened, so two proxied instances "colliding" is harmless (both reach the
                # controller's one real connection either way).
                self._by_id[iid] = ProxiedInstrument(
                    iid, library=entry.get("library_id", lib_id),
                    capabilities=list(entry.get("capabilities", [])),
                    simulated=cfg.get("simulated", True), bridge=bridge, station=station,
                )
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
        """Per-instance state for the UI + health (§5.2, §6). `_declaration` is looked up
        on the INSTANCE first (falls through to the class for a real InstrumentBase, which
        only ever carries the class-level declaration the @instrument_library decorator
        set; a ProxiedInstrument carries its own per-instance declaration since one shared
        proxy class stands in for many different libraries)."""
        live = [{
            "id": i.instance_id,
            "library": getattr(i, "_declaration", {}).get("library_id"),
            "capabilities": getattr(i, "_declaration", {}).get("capabilities", []),
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

    async def refresh_proxied_status(self) -> None:
        """Ask the controller for the LIVE state of every proxied instance, one batched
        round trip. Best-effort and never raises — this backs a plain status GET, and a
        controller that isn't up yet (or a slow reply) just leaves the last-known state in
        place; the next call corrects it. No-op when nothing is proxied."""
        proxied = {iid: inst for iid, inst in self._by_id.items() if isinstance(inst, ProxiedInstrument)}
        if not proxied or self._bridge is None:
            return
        try:
            reply = await self._bridge.request("instrument.status", {"ids": list(proxied)},
                                               station=self._station, timeout=5.0)
        except Exception as exc:  # noqa: BLE001 — best-effort; keep last-known state
            self.diag.warning("variables", "instrument status refresh failed", error=str(exc))
            return
        rows = ((reply or {}).get("result") or {}).get("instances") or []
        for row in rows:
            inst = proxied.get(row.get("id"))
            if inst is not None and "state" in row:
                inst.state = row["state"]

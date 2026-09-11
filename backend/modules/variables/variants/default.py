"""variables `default` variant — the variable engine wired into the app.

Builds instrument instances from config (via the instrumentlib registry), exposes the
scalar `variable.*` verbs to LabVIEW over the bridge (Py-served `query/{op}`,
LABVIEW_BRIDGE §5), and a REST surface for the maintenance/human path. Non-scalar
capabilities are NOT here — they go through `capability.request` (§2.2, arriving IL4).

Also relays live station-variable values to the operator window (`/instruments/values/ws`):
subscribes `value/#`, caches the latest frame per (station, name), fans out over a WebSocket.
Controller-agnostic — the Python controller retained-publishes `value/{name}` on every step
read/write (controller/serve.py) independent of what kind of instrument is behind it, so this
has nothing to do with DAQ/LabVIEW hardware specifically. Migrated here from the (removed) `daq`
module, which is where it happened to live before `variables` existed; `Runs`/`Maintenance`'s
live-values panel (`useValues("/instruments/values/ws")`) depends on it.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.streaming import StreamHub
from instrumentlib.registry import build_index
from modules.variables.api import build_router
from modules.variables.engine import VariableEngine
from modules.variables.instances import InstanceRegistry


class BindingUnknownInstance(Exception):
    """Binding references an instance that isn't loaded (add it + restart first)."""

    def __init__(self, instance_id: str) -> None:
        super().__init__(f"instance '{instance_id}' is not loaded — add it and restart the backend")
        self.instance_id = instance_id


class DefaultVariables:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self._load_libraries()          # fills the instrumentlib registry BEFORE building instances
        self.instances = InstanceRegistry(core.diag)
        # One map per station (MULTI_STATION.md §4.2). The app.json `variables` block is a
        # single map applied to the default (first) socket — the single-station case; the
        # multi-station maps are authored per station as DB bindings. `station` is optional
        # everywhere and defaults to the first socket, so a single-station front end never
        # needs to send it.
        _one = getattr(core, "station", "") or ""
        self._stations: list[str] = list(getattr(core, "stations", None) or ([_one] if _one else []) or ["st1"])
        self._default_station = self._stations[0]
        maps: dict[str, dict] = {st: {} for st in self._stations}
        maps[self._default_station].update(dict(config.get("variables", {}) or {}))
        self.engine = VariableEngine(self.instances, maps, core.diag, default_station=self._default_station)
        # Static (app.json) bindings are read-only in the UI; operator-authored ones are
        # DB records (type "variable"), loaded over them at start() and editable.
        self._static_vars: dict = dict(config.get("variables", {}) or {})
        self._db_vars: set[tuple[str, str]] = set()   # (station, name)
        self._instance_stations: dict[str, list[str]] = {}   # id -> sockets (no-lease rule)
        self.router = build_router(self)
        self._values_hub = StreamHub()            # value/{name} -> /instruments/values/ws
        self._values: dict[tuple, dict] = {}       # (station, name) -> latest frame (snapshot)
        self.mqtt_handlers: list = [("value/#", self._on_value)]

    def _load_libraries(self) -> None:
        """Import the external instrument-library package(s) so their registration
        decorators fire (INSTRUMENT_LIBRARY.md §10). `library_paths` are added to
        sys.path (the sibling library repo); `library_packages` are imported.

        The repo-root `instrument_libs/` (drivers a fork COPIED from the central
        Instrument_Library, TEMPLATE.md §1.2) is auto-discovered — no app.json wiring
        needed: every fork's copied drivers show up in the Instruments config UI."""
        paths = list(self.config.get("library_paths", []))
        packages = list(self.config.get("library_packages", []))
        repo_root = Path(__file__).resolve().parents[4]        # …/backend/modules/variables/variants
        app_libs = repo_root / "instrument_libs"
        if (app_libs / "__init__.py").is_file():               # source: add the repo root to sys.path
            if str(repo_root) not in paths:
                paths.append(str(repo_root))
            if "instrument_libs" not in packages:
                packages.append("instrument_libs")
        elif importlib.util.find_spec("instrument_libs") is not None:   # frozen: compiled into the exe
            if "instrument_libs" not in packages:
                packages.append("instrument_libs")
        for p in paths:
            if Path(p).is_dir() and p not in sys.path:
                sys.path.insert(0, p)
        for pkg in packages:
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
        self._instance_stations = {c["id"]: list(c.get("stations") or self._stations)
                                   for c in configs if c.get("id")}
        # Single-client-instrument race fix (instances.py module docstring): under a
        # supervised Python controller, that subprocess already owns the one live
        # connection to every owner=python instrument — this registry must never open a
        # second one. Proxy through the bridge instead; under "labview" there is no
        # controller to proxy through, so instances connect directly as before.
        proxy_bridge = self.core.bridge if self.core.controller_kind == "python" else None
        self.instances.build(configs, on_command=self._on_cmd,
                             bridge=proxy_bridge, station=self._default_station)
        await self.instances.connect_all()
        await self._load_db_bindings()
        self._validate_no_lease()      # §9.3 shared-instrument rule, loud at startup
        b = self.core.bridge
        if b is not None:
            # The controller reads app-owned scalar signals through the variable engine;
            # `station` is passed by the bridge (MultiStationBridge.serve) so resolution
            # is against the calling socket's map.
            b.serve("variable.read", lambda a, st=None: self.engine.read(a["name"], st))
            b.serve("variable.write", lambda a, st=None: self.engine.write(a["name"], a["value"], st))
            b.serve("variable.read_many", lambda a, st=None: self.engine.read_many(a.get("names", []), st))
            b.serve("variable.write_many", lambda a, st=None: self.engine.write_many(a.get("values", {}), st))
            # Non-scalar actions bypass the variable engine (§2.2), by instance id.
            b.serve("capability.request", lambda a, st=None: self.call(a["instance"], a["method"], a.get("args")))

    async def call(self, instance_id: str, method: str, args=None) -> dict:
        """capability.request seam (§2.3): a non-scalar action on an instance by id."""
        inst = self.instances.require(instance_id)
        result = await inst.invoke(method, *(args or []))
        return {"instance": instance_id, "method": method, "result": result}

    def libraries(self) -> dict:
        return build_index()

    def capabilities(self) -> dict:
        """Capability UI catalog for the Instrument Test Bench (method → control)."""
        from modules.variables import capabilities as cap
        return cap.catalog()

    def instance_status(self) -> list[dict]:
        return self.instances.status()

    async def refresh_instance_status(self) -> None:
        """Live-refresh proxied instances' state before instance_status() is read for
        display (GET /variables/instances) — a no-op when controller.kind != "python"."""
        await self.instances.refresh_proxied_status()

    # --- live values relay (operator window) --------------------------------

    @staticmethod
    def _station_of(topic: str) -> str | None:
        parts = topic.split("/")
        return parts[1] if len(parts) > 2 and parts[0] == "tmf" else None

    def _on_value(self, topic: str, payload: dict | None) -> None:
        # value topic = tmf/{station}/value/{name}; cache latest per (station,name) + fan out.
        if payload is None:
            return
        station = self._station_of(topic)
        name = topic.split("value/", 1)[-1]
        frame = {"name": name, "station": station, **payload}
        self._values[(station, name)] = frame
        self._values_hub.broadcast(frame)

    async def stream_values_ws(self, ws: WebSocket) -> None:
        """Live station variable values for the operator window (Runs/Maintenance live-values
        panel). Snapshot-on-join (every cached value), then live value/{name} updates.
        `?station=` filters (MULTI_STATION.md §5)."""
        await ws.accept()
        station = ws.query_params.get("station")
        for frame in list(self._values.values()):
            if station and frame.get("station") != station:
                continue
            await ws.send_json(frame)
        async with self._values_hub.subscription() as q:
            try:
                while True:
                    frame = await q.get()
                    if station and frame.get("station") != station:
                        continue
                    await ws.send_json(frame)
            except WebSocketDisconnect:
                pass

    # --- variable-map editor (DB-backed bindings per station, super_admin) ---

    def _resolve_station(self, station: str | None) -> str:
        """Optional station -> a real socket (single-station front ends omit it)."""
        st = station or self._default_station
        if st not in self._stations:
            from modules.variables import bindings
            raise bindings.BindingError(f"unknown station '{st}' (have {self._stations})")
        return st

    async def _load_db_bindings(self) -> None:
        """Load operator-authored per-station bindings from the DB over the static map.
        A legacy record without `station` lands on the default socket."""
        try:
            rows = await self.core.db.repo.query("variable")
        except Exception as exc:  # noqa: BLE001 — no DB / fresh station: static map only
            self.core.diag.warning("variables", "binding load skipped", error=str(exc))
            return
        for r in rows:
            data = dict(r["data"])
            name = data.pop("name", r["id"])
            station = data.pop("station", None) or self._default_station
            self.engine.map_for(station)[name] = data
            self._db_vars.add((station, name))

    def _validate_no_lease(self) -> None:
        """§9.3: a shared instrument (>1 socket) may only be bound read-only. A write
        signal (or, later, a non-scalar action) on a shared instance is refused, loud —
        it prevents a configure-then-read interleaving across sockets (silent wrong PASS)."""
        from modules.variables import bindings
        for station, m in self.engine.maps.items():
            for name, v in m.items():
                err = self._no_lease_violation(v)
                if err:
                    raise bindings.BindingError(f"{station}:{name}: {err}")

    def _no_lease_violation(self, binding: dict) -> str | None:
        inst = binding.get("instance")
        stations = self._instance_stations.get(inst, self._stations)
        if len(stations) > 1 and binding.get("write"):
            return (f"instrument '{inst}' is shared across {stations}; a write binding is "
                    "refused (shared instruments bind read-only, PYTHON_CONTROLLER.md §9.3)")
        return None

    def _caps(self, instance_id: str) -> list[str] | None:
        """Declared capabilities of a loaded instance, or None if not loaded."""
        st = {s["id"]: s for s in self.instance_status()}.get(instance_id)
        if st is None or st.get("state") == "skipped":
            return None
        return list(st.get("capabilities") or [])

    def bindable(self, instance_id: str) -> dict:
        """Read/write methods a variable can bind on this instance (drives the form)."""
        from modules.variables import bindings
        caps = self._caps(instance_id)
        if caps is None:
            raise BindingUnknownInstance(instance_id)
        shared = len(self._instance_stations.get(instance_id, self._stations)) > 1
        b = bindings.bindable_for(caps)
        if shared:
            b["write"] = []   # shared instruments bind read-only (§9.3)
        return {"instance": instance_id, "capabilities": caps, "shared": shared, **b}

    def list_bindings(self, station: str | None = None) -> list[dict]:
        """Every variable on a station with its full binding + whether it is editable."""
        st = self._resolve_station(station)
        out = []
        for name, v in sorted(self.engine.map_for(st).items()):
            out.append({
                "name": name, "station": st, "instance": v.get("instance"),
                "read": v.get("read"), "write": v.get("write"),
                "args": v.get("args") or [], "units": v.get("units"),
                "scale": v.get("scale"), "clamp": v.get("clamp"),
                "editable": (st, name) in self._db_vars,
                "bound": self.instances.has(v.get("instance")),
            })
        return out

    async def save_binding(self, name: str, body: dict, *, is_new: bool) -> dict:
        from modules.variables import bindings
        name = (name or "").strip()
        station = self._resolve_station(body.get("station"))
        smap = self.engine.map_for(station)
        if is_new and name in smap:
            raise bindings.BindingError(f"variable '{name}' already exists on {station}")
        if not is_new and (station, name) not in self._db_vars:
            raise bindings.BindingError(f"'{name}' is not an editable (DB) binding on {station}")
        instance = (body.get("instance") or "").strip()
        caps = self._caps(instance)
        if caps is None:
            raise BindingUnknownInstance(instance)
        rec = bindings.validate(name, {**body, "instance": instance}, caps)
        violation = self._no_lease_violation(rec)
        if violation:
            raise bindings.BindingError(violation)
        await self.core.db.repo.put("variable", {**rec, "name": name, "station": station},
                                    id=f"{station}:{name}",
                                    summary=f"{station} {instance}:{rec.get('read') or rec.get('write')}")
        smap[name] = rec          # hot-apply, no restart
        self._db_vars.add((station, name))
        self.core.diag.info("variables", "binding saved", name=name, station=station, instance=instance)
        return {"name": name, "station": station, **rec, "editable": True}

    async def delete_binding(self, name: str, station: str | None = None) -> bool:
        st = self._resolve_station(station)
        if (st, name) not in self._db_vars:
            return False
        await self.core.db.repo.delete_id("variable", f"{st}:{name}")
        self._db_vars.discard((st, name))
        smap = self.engine.map_for(st)
        if st == self._default_station and name in self._static_vars:
            smap[name] = dict(self._static_vars[name])   # restore app.json binding
        else:
            smap.pop(name, None)
        self.core.diag.info("variables", "binding deleted", name=name, station=st)
        return True

    async def stop(self) -> None:
        await self.instances.disconnect_all()

    async def health(self) -> Health:
        unbound = self.engine.unbound()
        n = len(self.instances.all())
        if unbound:
            return Health(status=HealthStatus.DEGRADED,
                          detail=f"{n} instances · unbound: {', '.join(unbound)}")
        return Health(status=HealthStatus.OK, detail=f"{n} instances · {self.engine.count()} variables")

    # readiness: unbound variable names block /readyz, loudly (§5.3)
    async def ready(self) -> bool:
        return not self.engine.unbound()

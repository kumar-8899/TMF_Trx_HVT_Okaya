"""The reflex loop (PYTHON_CONTROLLER.md §10.3).

Runs on its OWN thread, independent of any sequencer thread, and MUST NOT depend on the
bridge (INSTRUMENT_LIBRARY.md §1): the emergency_disable() fan-out goes straight to the
instrument loop, so it fires even if the broker is gone. A trip may be *requested* over the
bridge (a manual E-stop op) or by a product detector — either way `trip()` only enqueues,
and the reflex thread does the work, in order:

    1. emergency_disable() fan-out across the blast radius — immediate, ahead of all else
    2. resources marked faulted (further use fails fast until an operator clears them)
    3. event/safety-trip published (no run_id — a station fact, not a run fact)
    4. affected stations -> aborting, teardown SKIPPED, -> faulted

Steps 3–4 touch the bridge; they come *after* the hardware is safe, so a dead broker delays
notification but never the disable."""

from __future__ import annotations

import queue
import threading
import time

_STOP = object()


class SafetyController:
    def __init__(self, safety_map, registry, loop, engines: dict, publish_station, *, log=None):
        self._map = safety_map
        self._registry = registry
        self._loop = loop                    # AsyncLoopThread — the instrument I/O loop
        self._engines = dict(engines)        # station -> RunEngine
        self._publish = publish_station       # (station, subtopic, payload) -> None
        self._log = log
        self._q: "queue.Queue" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="safety-reflex", daemon=True)
        self._tripped: dict[str, float] = {}  # monitor_id -> ts of last trip

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._q.put(_STOP)
        self._thread.join(timeout=5.0)

    # ---- served / trip source (safe to call from any thread) -------------
    def trip(self, monitor_id: str) -> dict:
        """Enqueue a trip; the reflex thread executes it. Returns at once so a bridge
        callback is never blocked by the fan-out."""
        if monitor_id is None:
            return {"ok": False, "error": "trip needs 'monitor_id'"}
        if self._map.radius(monitor_id) is None:
            return {"ok": False, "error": f"unknown safety monitor '{monitor_id}'"}
        self._q.put(monitor_id)
        return {"ok": True, "accepted": True, "monitor_id": monitor_id}

    def clear(self, monitor_id: str) -> dict:
        """Operator clears a trip's faulted resources + stations (maintenance mode; the
        MAINTENANCE.* gate is enforced app-side, §10.4)."""
        r = self._map.radius(monitor_id)
        if r is None:
            return {"ok": False, "error": f"unknown safety monitor '{monitor_id}'"}
        self._registry.clear_faulted(r.instances)
        cleared = [st for st in r.stations
                   if (eng := self._engines.get(st)) and eng.clear_fault().get("cleared")]
        self._tripped.pop(monitor_id, None)
        self._emit_log("info", f"safety cleared '{monitor_id}': stations {cleared}")
        return {"ok": True, "cleared_stations": cleared, "cleared_resources": r.instances}

    def status(self) -> dict:
        return {"monitors": self._map.describe(), "faulted_resources": self._registry.faulted(),
                "faulted_stations": [st for st, e in self._engines.items() if e.state == "faulted"],
                "tripped": sorted(self._tripped)}

    # ---- the reflex thread ----------------------------------------------
    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                return
            try:
                self.handle_trip(item)
            except Exception as exc:  # noqa: BLE001 — the reflex thread must never die
                self._emit_log("error", f"reflex trip '{item}' failed: {exc}")

    def handle_trip(self, monitor_id: str) -> None:
        """The fan-out, in §10.3 order. Public so tests can drive it synchronously."""
        r = self._map.radius(monitor_id)
        if r is None:
            self._emit_log("error", f"trip for unknown monitor '{monitor_id}'")
            return
        self._tripped[monitor_id] = time.time()

        # 1. emergency_disable — immediate, straight to the instrument loop (no bridge)
        instances = [i for i in (self._registry.get(iid) for iid in r.instances) if i is not None]
        try:
            self._loop.run(self._registry.emergency_disable(instances), timeout=5.0)
        except Exception as exc:  # noqa: BLE001 — a stuck disable must not stop the fault fan-out
            self._emit_log("error", f"emergency_disable during '{monitor_id}' failed: {exc}")
        # 2. resources faulted — further use fails fast until cleared
        self._registry.mark_faulted(r.instances)
        self._emit_log("warning",
                       f"SAFETY TRIP '{monitor_id}' ({r.scope}): stations {r.stations}, "
                       f"resources {r.instances} — outputs disabled, teardown skipped")

        # 3. event/safety-trip on each affected station — no run_id (§6 rule 3)
        payload = {"monitor_id": monitor_id, "scope": r.scope,
                   "stations": r.stations, "resources": r.instances}
        for st in r.stations:
            self._publish(st, "event/safety-trip",
                          {"type": "safety-trip", "ts": time.time(),
                           "trace": f"safety:{monitor_id}", "payload": payload})
        # 4. affected stations -> aborting -> faulted (teardown skipped inside the engine)
        for st in r.stations:
            eng = self._engines.get(st)
            if eng is not None:
                eng.safety_trip(monitor_id)

    def _emit_log(self, level: str, message: str) -> None:
        if self._log:
            self._log(level, message)

"""Per-station variable engine (INSTRUMENT_LIBRARY.md §5.3, PYTHON_CONTROLLER.md §4.1).

One map per station, same names across identical sockets, so a recipe/handler names a
signal and resolution happens against the calling station's map. Signals are scalar
(read/write with scale + clamp); actions (non-scalar capabilities) are parsed but reached
via ctx.invoke — that path lands in C9. Read: lookup -> capability call -> raw*gain+offset.
Write: clamp -> inverse scale -> capability call.

Sync-facing: instrument calls are async (instrumentlib), dispatched to the shared loop so
MQTT-callback and station threads can call read()/write() directly."""

from __future__ import annotations

import json
from pathlib import Path


class VariableError(Exception):
    """Unknown signal, or a read/write against a direction it does not declare."""


def check_no_lease(instrument_stations: dict[str, list[str]], station_maps: dict[str, dict]) -> list[str]:
    """The shared-instrument no-lease rule (PYTHON_CONTROLLER.md §9.3). A shared instrument
    (serves >1 socket) may only be bound read-only: a signal with `write`, or any action,
    is refused — per-call atomicity doesn't stop a configure-then-read interleaving across
    sockets, and that is a silent wrong PASS. Three checks, at config load, loud."""
    errors: list[str] = []
    for station, vmap in station_maps.items():
        for name, b in (vmap.get("signals") or {}).items():
            inst = b.get("instance")
            if len(instrument_stations.get(inst, [])) > 1 and b.get("write"):
                errors.append(f"{station}:{name}: write binding on shared instrument "
                              f"'{inst}' {instrument_stations.get(inst)} — refused (§9.3)")
        for name, a in (vmap.get("actions") or {}).items():
            inst = a.get("instance")
            if len(instrument_stations.get(inst, [])) > 1:
                errors.append(f"{station}:{name}: action on shared instrument "
                              f"'{inst}' {instrument_stations.get(inst)} — refused (§9.3)")
    return errors


def load_variable_map(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise VariableError(f"variable map not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return {"signals": data.get("signals", {}) or {}, "actions": data.get("actions", {}) or {}}


def _scale(v: dict) -> tuple[float, float]:
    s = v.get("scale") or {}
    return float(s.get("gain", 1.0)), float(s.get("offset", 0.0))


def _clamp(v: dict, value: float) -> tuple[float, bool]:
    c = v.get("clamp")
    if not c:
        return value, False
    out = value
    if c.get("min") is not None:
        out = max(out, float(c["min"]))
    if c.get("max") is not None:
        out = min(out, float(c["max"]))
    return out, out != value


class StationVariables:
    def __init__(self, station: str, varmap: dict, registry, loop, *, call_timeout: float = 10.0):
        self.station = station
        self.signals: dict[str, dict] = varmap.get("signals", {})
        self.actions: dict[str, dict] = varmap.get("actions", {})
        self._registry = registry
        self._loop = loop
        self._timeout = call_timeout

    def _sig(self, name: str) -> dict:
        v = self.signals.get(name)
        if v is None:
            raise VariableError(f"unknown signal '{name}' on {self.station}")
        return v

    def _invoke(self, instance_id: str, method: str, *args):
        inst = self._registry.require(instance_id)
        return self._loop.run(inst.invoke(method, *args), timeout=self._timeout)

    def read(self, name: str) -> dict:
        v = self._sig(name)
        if not v.get("read"):
            raise VariableError(f"signal '{name}' is not readable")
        raw = self._invoke(v["instance"], v["read"], *(v.get("args") or []))
        gain, offset = _scale(v)
        return {"name": name, "value": raw * gain + offset, "raw": raw, "units": v.get("units")}

    def write(self, name: str, value: float) -> dict:
        v = self._sig(name)
        if not v.get("write"):
            raise VariableError(f"signal '{name}' is not writable")
        clamped, was_clamped = _clamp(v, float(value))
        gain, offset = _scale(v)
        scaled = (clamped - offset) / gain if gain else clamped
        self._invoke(v["instance"], v["write"], *(v.get("args") or []), scaled)
        return {"name": name, "written": clamped, "requested": value, "clamped": was_clamped}

    def list(self) -> list[dict]:
        return [{"name": n, "instance": v["instance"], "units": v.get("units"),
                 "readable": bool(v.get("read")), "writable": bool(v.get("write"))}
                for n, v in sorted(self.signals.items())]

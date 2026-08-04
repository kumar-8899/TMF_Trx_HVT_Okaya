"""The variable engine — one map per station (INSTRUMENT_LIBRARY.md §5.3,
MULTI_STATION.md §4.2).

Names scalar signals so recipes/handlers reference names, never hardware. Each station
has its own map; the SAME name resolves to a station-specific instance, so one recipe
runs unchanged on any socket. Resolution is always against the calling station's map;
when the app runs a single socket, `station` is optional and defaults to it (the front
end can stay station-unaware). Read: lookup → capability call → raw*gain+offset. Write:
clamp (silent, logged) → inverse scale → capability call.
"""

from __future__ import annotations

from instrumentlib.errors import InstrumentError


class VariableError(InstrumentError):
    """Unknown variable, unknown station, or a read/write against a direction it doesn't declare."""


class VariableEngine:
    def __init__(self, instances, maps: dict[str, dict], diag, default_station: str = ""):
        self.instances = instances
        self.maps: dict[str, dict] = maps or {}
        self.diag = diag
        self.default_station = default_station

    # ---- station resolution ----------------------------------------------

    def _station(self, station: str | None) -> str:
        return station or self.default_station

    def map_for(self, station: str | None) -> dict:
        return self.maps.setdefault(self._station(station), {})

    # ---- introspection ----------------------------------------------------

    def list(self, station: str | None = None) -> list[dict]:
        out = []
        for name, v in self.map_for(station).items():
            out.append({
                "name": name, "instance": v["instance"], "units": v.get("units"),
                "readable": bool(v.get("read")), "writable": bool(v.get("write")),
                "bound": self.instances.has(v["instance"]),
            })
        return sorted(out, key=lambda x: x["name"])

    def unbound(self) -> list[str]:
        """`station:name` for every binding whose instance isn't loaded (blocks /readyz)."""
        out = []
        for st, m in self.maps.items():
            for n, v in m.items():
                if not self.instances.has(v["instance"]):
                    out.append(f"{st}:{n}")
        return sorted(out)

    def count(self) -> int:
        return sum(len(m) for m in self.maps.values())

    # ---- scalar read/write ------------------------------------------------

    def _var(self, name: str, station: str | None) -> dict:
        v = self.map_for(station).get(name)
        if v is None:
            raise VariableError(f"unknown variable '{name}' on station '{self._station(station)}'",
                                method="read")
        return v

    async def read(self, name: str, station: str | None = None) -> dict:
        v = self._var(name, station)
        if not v.get("read"):
            raise VariableError(f"variable '{name}' is not readable", method="read")
        inst = self.instances.require(v["instance"])
        raw = await inst.invoke(v["read"], *(v.get("args") or []))
        gain, offset = _scale(v)
        return {"name": name, "value": raw * gain + offset, "raw": raw, "units": v.get("units")}

    async def write(self, name: str, value: float, station: str | None = None) -> dict:
        v = self._var(name, station)
        if not v.get("write"):
            raise VariableError(f"variable '{name}' is not writable", method="write")
        clamped, was_clamped = _clamp(v, float(value))
        if was_clamped:
            self.diag.warning("variables", "value clamped", name=name, station=self._station(station),
                              requested=value, written=clamped, **_clamp_bounds(v))
        gain, offset = _scale(v)
        scaled = (clamped - offset) / gain if gain else clamped
        inst = self.instances.require(v["instance"])
        await inst.invoke(v["write"], *(v.get("args") or []), scaled)
        return {"name": name, "written": clamped, "requested": value, "clamped": was_clamped}

    async def read_many(self, names: list[str], station: str | None = None) -> dict:
        return {n: await self.read(n, station) for n in names}

    async def write_many(self, values: dict, station: str | None = None) -> dict:
        return {n: await self.write(n, val, station) for n, val in values.items()}


def _scale(v: dict) -> tuple[float, float]:
    s = v.get("scale") or {}
    return float(s.get("gain", 1.0)), float(s.get("offset", 0.0))


def _clamp_bounds(v: dict) -> dict:
    c = v.get("clamp") or {}
    return {"min": c.get("min"), "max": c.get("max")}


def _clamp(v: dict, value: float) -> tuple[float, bool]:
    c = v.get("clamp")
    if not c:
        return value, False
    lo, hi = c.get("min"), c.get("max")
    out = value
    if lo is not None:
        out = max(out, float(lo))
    if hi is not None:
        out = min(out, float(hi))
    return out, out != value

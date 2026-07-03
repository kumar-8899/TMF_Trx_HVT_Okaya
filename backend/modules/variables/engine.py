"""The variable engine — the surviving ~200 lines (INSTRUMENT_LIBRARY.md §5.3).

Names signals so recipes/sequencer reference names, never hardware. Read: lookup →
capability call → raw*gain+offset. Write: clamp (silent, logged; returned so a step
can detect it) → inverse scale → capability call. A vendor swap is one station-config
edit and zero recipe changes. Non-scalar capabilities are NEVER bound here (§2.2).
"""

from __future__ import annotations

from instrumentlib.errors import InstrumentError


class VariableError(InstrumentError):
    """Unknown variable, or a read/write against a direction it doesn't declare."""


class VariableEngine:
    def __init__(self, instances, varmap: dict, diag):
        self.instances = instances
        self.vars: dict[str, dict] = varmap or {}
        self.diag = diag

    # ---- introspection (GET /variables) -----------------------------------

    def list(self) -> list[dict]:
        out = []
        for name, v in self.vars.items():
            out.append({
                "name": name, "instance": v["instance"], "units": v.get("units"),
                "readable": bool(v.get("read")), "writable": bool(v.get("write")),
                "bound": self.instances.has(v["instance"]),
            })
        return sorted(out, key=lambda x: x["name"])

    def unbound(self) -> list[str]:
        """Variables whose instance isn't loaded (blocks /readyz, §5.3)."""
        return sorted(n for n, v in self.vars.items() if not self.instances.has(v["instance"]))

    # ---- scalar read/write ------------------------------------------------

    def _var(self, name: str) -> dict:
        v = self.vars.get(name)
        if v is None:
            raise VariableError(f"unknown variable '{name}'", method="read")
        return v

    async def read(self, name: str) -> dict:
        v = self._var(name)
        if not v.get("read"):
            raise VariableError(f"variable '{name}' is not readable", method="read")
        inst = self.instances.require(v["instance"])
        raw = await inst.invoke(v["read"])
        gain, offset = _scale(v)
        return {"name": name, "value": raw * gain + offset, "raw": raw, "units": v.get("units")}

    async def write(self, name: str, value: float) -> dict:
        v = self._var(name)
        if not v.get("write"):
            raise VariableError(f"variable '{name}' is not writable", method="write")
        clamped, was_clamped = _clamp(v, float(value))
        if was_clamped:
            self.diag.warning("variables", "value clamped", name=name,
                              requested=value, written=clamped, **_clamp_bounds(v))
        gain, offset = _scale(v)
        scaled = (clamped - offset) / gain if gain else clamped   # inverse scale
        inst = self.instances.require(v["instance"])
        await inst.invoke(v["write"], scaled)
        return {"name": name, "written": clamped, "requested": value, "clamped": was_clamped}

    async def read_many(self, names: list[str]) -> dict:
        return {n: await self.read(n) for n in names}

    async def write_many(self, values: dict) -> dict:
        return {n: await self.write(n, val) for n, val in values.items()}


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

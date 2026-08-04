"""Variable-map binding rules — the editor's validation layer.

A binding maps a scalar signal name -> an instrument capability method (+ fixed
leading args like a channel, units, scale, clamp). The set of *bindable* methods for
an instance is derived from its declared capabilities via the same CAPABILITY_UI
catalog that drives the Test Bench (`modules/variables/capabilities.py`) — the library
is the source of truth for how it can be addressed, so the editor never free-types a
method name.

Only numeric scalar methods bind here (the variable engine scales/clamps floats):
  readable  = catalog kind "read"   (measure_*, get_*_setpoint, read_*)
  writable  = catalog kind "set"    (set_voltage, set_current_limit, write_digital)
Toggles/enums are intentionally excluded — they are hands-on, non-scalar controls and
belong on the Test Bench, not in the numeric variable map (§2.2).
"""

from __future__ import annotations

import re

from modules.variables.capabilities import CAPABILITY_UI

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class BindingError(Exception):
    """Rejected binding input (bad name, unknown method, wrong arg count)."""


def _entry(cap: str, m: dict, fixed: list[dict]) -> dict:
    return {"capability": cap, "method": m["method"], "label": m["label"],
            "unit": m.get("unit"), "args": m.get("args", []), "fixed_args": fixed}


def bindable_for(capabilities: list[str]) -> dict:
    """The read/write methods a variable can bind on an instrument with these
    capabilities. `fixed_args` are the leading positional args the binding supplies
    (a read binds all its args; a setpoint binds all but the trailing value)."""
    read: list[dict] = []
    write: list[dict] = []
    seen_r: set[str] = set()
    seen_w: set[str] = set()
    for cap in capabilities or []:
        ui = CAPABILITY_UI.get(cap)
        if not ui:
            continue
        for m in ui["methods"]:
            name, kind, args = m["method"], m["kind"], m.get("args", [])
            if kind == "read" and name not in seen_r:
                read.append(_entry(cap, m, list(args)))
                seen_r.add(name)
            elif kind == "set" and name not in seen_w:
                write.append(_entry(cap, m, list(args[:-1])))   # last arg is the value
                seen_w.add(name)
    return {"read": read, "write": write}


def _coerce(arg: dict, value):
    t = arg.get("type", "number")
    if value in (None, ""):
        raise BindingError(f"arg '{arg['name']}' is required")
    try:
        if t == "int":
            return int(value)
        if t == "bool":
            return bool(value)
        if t == "number":
            return float(value)
    except (TypeError, ValueError) as exc:
        raise BindingError(f"arg '{arg['name']}' must be {t}") from exc
    return value


def validate(name: str, body: dict, capabilities: list[str]) -> dict:
    """Validate + normalise a binding into the engine's varmap shape:
    `{instance, read?, write?, args, units?, scale?, clamp?}`. Raises BindingError."""
    if not _NAME_RE.match(name or ""):
        raise BindingError("name must match ^[a-z][a-z0-9_]{0,63}$")
    b = bindable_for(capabilities)
    rmap = {m["method"]: m for m in b["read"]}
    wmap = {m["method"]: m for m in b["write"]}
    read = (body.get("read") or "").strip() or None
    write = (body.get("write") or "").strip() or None
    if not read and not write:
        raise BindingError("a binding needs a read method, a write method, or both")
    if read and read not in rmap:
        raise BindingError(f"'{read}' is not a readable signal on this instrument")
    if write and write not in wmap:
        raise BindingError(f"'{write}' is not a writable setpoint on this instrument")

    primary = rmap.get(read) or wmap.get(write)
    fixed = primary["fixed_args"]
    if read and write and len(rmap[read]["fixed_args"]) != len(wmap[write]["fixed_args"]):
        raise BindingError("read and write take different fixed args — use separate variables")

    args_in = body.get("args") or []
    if len(args_in) != len(fixed):
        names = ", ".join(a["name"] for a in fixed) or "none"
        raise BindingError(f"expected {len(fixed)} fixed arg(s): {names}")
    args = [_coerce(a, v) for a, v in zip(fixed, args_in)]

    out: dict = {"instance": body["instance"], "args": args}
    if read:
        out["read"] = read
    if write:
        out["write"] = write
    units = (body.get("units") or "").strip()
    out["units"] = units or primary.get("unit") or None

    scale = body.get("scale") or {}
    if scale.get("gain") not in (None, "") or scale.get("offset") not in (None, ""):
        out["scale"] = {"gain": float(scale.get("gain", 1.0) or 1.0),
                        "offset": float(scale.get("offset", 0.0) or 0.0)}
    clamp = body.get("clamp") or {}
    c: dict = {}
    if clamp.get("min") not in (None, ""):
        c["min"] = float(clamp["min"])
    if clamp.get("max") not in (None, ""):
        c["max"] = float(clamp["max"])
    if "min" in c and "max" in c and c["min"] > c["max"]:
        raise BindingError("clamp min must be <= max")
    if c:
        out["clamp"] = c
    return out

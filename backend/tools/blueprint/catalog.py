"""Closed vocabularies the blueprint validates against — read LIVE from the framework
code so the template can never drift from what the variable engine actually accepts.

- Capability methods come from `modules.variables.capabilities.CAPABILITY_UI` (the same
  catalog that drives the Test Bench). Only scalar read/set methods are variable-bindable;
  toggle/enum/action kinds are excluded (they are non-scalar, hands-on controls).
- Transports come from `modules.config.transports.TRANSPORTS` (the instrument-form catalog).

Fixed-arg arity (the channel/sub-address count) matches the engine's calling convention
(`backend/modules/variables ... StationVariables`):
  * a READ method is called `invoke(read, *args)` — every declared arg is fixed;
  * a WRITE method is called `invoke(write, *args, value)` — the LAST declared arg is the
    written value, so its fixed-arg count is `len(args) - 1`.
`bindings.py` additionally requires a read+write signal to share the same fixed-arg arity.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def capability_methods() -> dict[str, dict]:
    """capability id -> {read: [names], write: [names], fixed: {method: n_fixed_args}}."""
    from modules.variables.capabilities import CAPABILITY_UI

    out: dict[str, dict] = {}
    for cap, spec in CAPABILITY_UI.items():
        reads: list[str] = []
        writes: list[str] = []
        fixed: dict[str, int] = {}
        for m in spec["methods"]:
            name = m["method"]
            n = len(m.get("args") or [])
            if m["kind"] == "read":
                reads.append(name)
                fixed[name] = n
            elif m["kind"] == "set":
                writes.append(name)
                fixed[name] = max(0, n - 1)  # last declared arg is the written value
            # toggle / enum / action kinds are non-scalar — never bound in the map
        out[cap] = {"read": reads, "write": writes, "fixed": fixed}
    return out


@lru_cache(maxsize=1)
def transports() -> dict[str, dict]:
    """transport id -> {required: [keys], fields: [keys]}."""
    from modules.config import transports as T

    return {
        t["id"]: {
            "required": [f["key"] for f in t["fields"] if f.get("required")],
            "fields": [f["key"] for f in t["fields"]],
        }
        for t in T.TRANSPORTS
    }


def read_methods_for(capabilities: list[str]) -> dict[str, int]:
    """Legal read methods (name -> fixed-arg count) across the given capabilities."""
    cat = capability_methods()
    out: dict[str, int] = {}
    for cap in capabilities:
        spec = cat.get(cap)
        if not spec:
            continue
        for name in spec["read"]:
            out[name] = spec["fixed"][name]
    return out


def write_methods_for(capabilities: list[str]) -> dict[str, int]:
    """Legal write methods (name -> fixed-arg count) across the given capabilities."""
    cat = capability_methods()
    out: dict[str, int] = {}
    for cap in capabilities:
        spec = cat.get(cap)
        if not spec:
            continue
        for name in spec["write"]:
            out[name] = spec["fixed"][name]
    return out


def all_capability_ids() -> list[str]:
    return sorted(capability_methods().keys())


def all_transport_ids() -> list[str]:
    return sorted(transports().keys())

"""Registration + generated index (INSTRUMENT_LIBRARY.md §5.1, §10).

`@instrument_library(...)` stamps a full provenance declaration onto the class and
records it in a global registry (duplicate `library_id` fails loudly). CI imports
the package tree so the decorators fire, then emits `index.json` — the machine
catalog the builder, the config form, and the tester consume. The index is a build
artifact, never hand-authored, so drift is structurally impossible.
"""

from __future__ import annotations

from instrumentlib.interfaces import CAPABILITIES

_REQUIRED = ("library_id", "vendor", "model", "capability", "interface_version",
             "transports", "library_version")

REGISTRY: dict[str, dict] = {}


def instrument_library(**decl):
    def deco(cls):
        missing = [k for k in _REQUIRED if k not in decl]
        if missing:
            raise ValueError(f"{cls.__name__}: declaration missing {missing}")
        cap = decl["capability"]
        if cap not in CAPABILITIES:
            raise ValueError(f"{cls.__name__}: unknown capability '{cap}'")
        lid = decl["library_id"]
        if lid in REGISTRY and REGISTRY[lid]["class"] is not cls:
            raise ValueError(f"duplicate library_id '{lid}' "
                             f"({REGISTRY[lid]['class'].__name__} vs {cls.__name__})")
        cls._declaration = dict(decl)
        REGISTRY[lid] = {"class": cls, **decl}
        return cls
    return deco


def build_index() -> dict:
    """The machine-readable catalog (identity, capability, params schema, 3 versions,
    provenance). Consumed by the builder app + the Instruments config page."""
    libs = []
    for d in REGISTRY.values():
        entry = {k: v for k, v in d.items() if k != "class"}
        entry.setdefault("scalar", d["capability"] in
                         {c for c in CAPABILITIES if CAPABILITIES[c].SCALAR})
        libs.append(entry)
    libs.sort(key=lambda e: e["library_id"])
    return {"schema_version": 1, "libraries": libs}


def _reset_registry() -> None:      # test hygiene
    REGISTRY.clear()

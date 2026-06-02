"""Manifest schema + loader (CORE.md §3.1).

A module's static JSON self-description. Loaded from the module's package dir,
validated against the core manifest schema. Paths (config_schema, migrations)
are resolved relative to that dir so the gate can use them directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as _SchemaError

CORE_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"
MODULES_DIR = Path(__file__).resolve().parents[2] / "modules"


class ManifestError(Exception):
    """Manifest missing or failed schema validation."""


@dataclass
class Contributes:
    api_prefix: str = ""
    mqtt_subscriptions: list[str] = field(default_factory=list)
    migrations: str | None = None
    frontend_flags: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    id: str
    version: str
    contract_version: int
    display_name: str
    description: str
    entitlement_key: str
    variants: list[str]
    core_dependencies: list[str]
    contract_dependencies: list[str]
    contributes: Contributes
    config_schema: str | None
    base_dir: Path

    @property
    def config_schema_path(self) -> Path | None:
        return self.base_dir / self.config_schema if self.config_schema else None

    @property
    def migrations_path(self) -> Path | None:
        return self.base_dir / self.contributes.migrations if self.contributes.migrations else None


class ManifestLoader:
    def __init__(self, modules_dir: Path | str = MODULES_DIR, schemas_dir: Path | str = CORE_SCHEMAS_DIR) -> None:
        self.modules_dir = Path(modules_dir)
        schema = json.loads((Path(schemas_dir) / "manifest.schema.json").read_text(encoding="utf-8"))
        self._validator = Draft202012Validator(schema)

    def load(self, module_id: str) -> Manifest:
        return self.load_path(self.modules_dir / module_id / "manifest.json")

    def load_path(self, path: Path | str) -> Manifest:
        path = Path(path)
        if not path.exists():
            raise ManifestError(f"manifest not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            self._validator.validate(raw)
        except _SchemaError as exc:
            loc = "/".join(str(p) for p in exc.absolute_path) or "(root)"
            raise ManifestError(f"manifest invalid at {loc}: {exc.message}") from exc

        m = raw["module"]
        c = raw.get("contributes", {})
        return Manifest(
            id=m["id"],
            version=m["version"],
            contract_version=m["contract_version"],
            display_name=m["display_name"],
            description=m.get("description", ""),
            entitlement_key=raw["entitlement_key"],
            variants=raw["variants"],
            core_dependencies=raw.get("core_dependencies", []),
            contract_dependencies=raw.get("contract_dependencies", []),
            contributes=Contributes(
                api_prefix=c.get("api_prefix", ""),
                mqtt_subscriptions=c.get("mqtt_subscriptions", []),
                migrations=c.get("migrations"),
                frontend_flags=c.get("frontend_flags", []),
            ),
            config_schema=raw.get("config_schema"),
            base_dir=path.parent,
        )

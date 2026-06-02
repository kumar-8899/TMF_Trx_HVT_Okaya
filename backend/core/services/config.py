"""Config service (CORE.md §1, PRINCIPLES.md §4).

JSON config validated by JSON Schema. Every file carries a `schema_version`
header. The live file is gitignored and copied from its `*.example.json` on
first run (the TOML convention, in JSON).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as _SchemaError

BACKEND_DIR = Path(__file__).resolve().parents[2]
CORE_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"
DEFAULT_CONFIG_DIR = BACKEND_DIR / "config"


class ConfigError(Exception):
    """Config missing or failed schema validation. Loud and structured (PRINCIPLES §6)."""


class ConfigService:
    def __init__(
        self,
        config_dir: Path | str = DEFAULT_CONFIG_DIR,
        schemas_dir: Path | str = CORE_SCHEMAS_DIR,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.schemas_dir = Path(schemas_dir)
        self._validators: dict[Path, Draft202012Validator] = {}

    # --- low level ---------------------------------------------------------

    def _validator(self, schema_path: Path) -> Draft202012Validator:
        schema_path = Path(schema_path)
        if schema_path not in self._validators:
            if not schema_path.exists():
                raise ConfigError(f"schema not found: {schema_path}")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self._validators[schema_path] = Draft202012Validator(schema)
        return self._validators[schema_path]

    def validate(self, instance: Any, schema_path: Path | str, *, what: str = "config") -> Any:
        try:
            self._validator(Path(schema_path)).validate(instance)
        except _SchemaError as exc:
            loc = "/".join(str(p) for p in exc.absolute_path) or "(root)"
            raise ConfigError(f"{what} invalid at {loc}: {exc.message}") from exc
        return instance

    def ensure_live(self, name: str) -> Path:
        """Copy `<name>.example.json` -> `<name>.json` if the live file is absent."""
        live = self.config_dir / f"{name}.json"
        if not live.exists():
            example = self.config_dir / f"{name}.example.json"
            if not example.exists():
                raise ConfigError(f"neither {live.name} nor {example.name} present in {self.config_dir}")
            shutil.copyfile(example, live)
        return live

    def load_json(self, path: Path | str) -> Any:
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"file not found: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path.name} is not valid JSON: {exc}") from exc

    # --- typed loads -------------------------------------------------------

    def load_app(self, name: str = "app") -> dict:
        path = self.ensure_live(name)
        data = self.load_json(path)
        return self.validate(data, self.schemas_dir / "app.schema.json", what="app config")

    def load_license(self, path: Path | str | None = None) -> dict:
        if path is None:
            path = self.ensure_live("license")
        else:
            path = Path(path)
            if not path.is_absolute():
                path = self.config_dir / path
        data = self.load_json(path)
        return self.validate(data, self.schemas_dir / "license.schema.json", what="license")

    def load_module(self, module_id: str, raw: dict, schema_path: Path | str | None) -> dict:
        """Validate a single module's config block against its declared schema."""
        if schema_path is None:
            return raw
        return self.validate(raw, schema_path, what=f"{module_id} config")

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
        data = self.validate(data, self.schemas_dir / "app.schema.json", what="app config")
        return self._normalise_stations(data)

    @staticmethod
    def _normalise_stations(data: dict) -> dict:
        """Multi-station migration (MULTI_STATION.md §1): a config carrying the old
        singular `station` is read as a one-element `stations` list. `station` is kept
        as an alias for the first socket so not-yet-converted single-station code paths
        keep working during the M1-M6 migration. `stations_migrated` flags the old form
        so the caller can emit a deprecation warning."""
        if "stations" not in data:
            st = data.get("station")
            data["stations"] = [st] if st else []
            data["stations_migrated"] = bool(st)
        if not data.get("station") and data["stations"]:
            data["station"] = data["stations"][0]
        return data

    def load_license(self, path: Path | str | None = None) -> dict:
        """The license lives beside app.json in the config dir; the directory part
        of the configured path is ignored (only the file name matters)."""
        if path is None:
            live = self.ensure_live("license")
        else:
            p = Path(path)
            if p.is_absolute():
                live = p
            else:
                target = self.config_dir / p.name
                live = target if target.exists() else self.ensure_live(p.stem)
        data = self.load_json(live)
        return self.validate(data, self.schemas_dir / "license.schema.json", what="license")

    def example_only_modules(self, name: str = "app") -> list[str]:
        """Module ids present in <name>.example.json but missing from the live
        <name>.json. ensure_live never refreshes an existing live file, so this
        surfaces stale live config after new modules are added."""
        live = self.config_dir / f"{name}.json"
        example = self.config_dir / f"{name}.example.json"
        if not live.exists() or not example.exists():
            return []

        def ids(path: Path) -> set[str]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return set()
            return {m.get("id") for m in data.get("modules", []) if m.get("id")}

        return sorted(ids(example) - ids(live))

    def _read(self, name: str) -> tuple[dict, dict]:
        """(live, example) parsed dicts for <name>.json / <name>.example.json ({} if absent)."""
        def read(p: Path) -> dict:
            try:
                return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except (json.JSONDecodeError, OSError):
                return {}
        return read(self.config_dir / f"{name}.json"), read(self.config_dir / f"{name}.example.json")

    @staticmethod
    def _roles(app: dict) -> dict:
        for m in app.get("modules", []):
            if m.get("id") == "auth":
                return (m.get("config", {}) or {}).get("roles", {}) or {}
        return {}

    def config_drift(self) -> dict:
        """What the live config is missing versus the example — surfaced loudly at
        boot so stale live config shows up as a warning, not a 403 later. Reports
        missing modules, roles, per-role permissions, and licensed modules.
        Live-only extras are never reported (the deployer may add their own)."""
        live, example = self._read("app")
        live_lic, ex_lic = self._read("license")
        if not example:
            return {"modules": [], "roles": [], "permissions": {}, "license_modules": []}

        modules = self.example_only_modules()

        lr, er = self._roles(live), self._roles(example)
        roles = sorted(set(er) - set(lr))
        perms: dict[str, list[str]] = {}
        for role in set(er) & set(lr):
            missing = sorted(set(er[role]) - set(lr[role]))
            if missing:
                perms[role] = missing

        def licensed(d: dict) -> set[str]:
            mods = ((d.get("entitlements", {}) or {}).get("modules", {}) or {})
            return {k for k, v in mods.items() if v}
        lic_modules = sorted(licensed(ex_lic) - licensed(live_lic)) if ex_lic else []

        return {"modules": modules, "roles": roles, "permissions": perms, "license_modules": lic_modules}

    def load_module(self, module_id: str, raw: dict, schema_path: Path | str | None) -> dict:
        """Validate a single module's config block against its declared schema."""
        if schema_path is None:
            return raw
        return self.validate(raw, schema_path, what=f"{module_id} config")

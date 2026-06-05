"""Recipe `filesystem` variant (RECIPE.md §12).

R1: discovers step types, builds the schema set, serves step-type introspection.
Authoring/versioning (R2), validation (R3), execution wire (R4), export/import
(R5), and diff (R6) extend this variant in later slices.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.recipe import registry as step_registry
from modules.recipe import export_import as ei
from modules.recipe.api import build_router
from modules.recipe.diff import diff_recipes, diff_summary
from modules.recipe.runtime_params import substitute
from modules.recipe.storage import (
    RecipeExistsError,
    RecipeStore,
    RecipeStoreError,
    RecipeValidationError,
)
from modules.recipe.validation.cross_reference import check_cross_references
from modules.recipe.validation.schema import SchemaSet
from modules.recipe.validation.semantic import check_semantic
from modules.recipe.versioning import content_hash


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FilesystemRecipe:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.station = core.station
        self.root = Path(config.get("root", "data/recipes"))
        self.store = RecipeStore(self.root)
        self._schemas: SchemaSet | None = None
        self.router = build_router(self)
        self.mqtt_handlers: list = []

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "FilesystemRecipe":
        return cls(core, config)

    async def init(self) -> None:
        step_registry.discover_step_types()  # populate the step-type registry
        self._schemas = SchemaSet()

    async def start(self) -> None:
        # R4 execution wire: serve recipe.fetch to LabVIEW (LV→Py query/{op}).
        if self.core.bridge is not None:
            self.core.bridge.serve("recipe.fetch", self._serve_fetch)

    async def stop(self) -> None:
        pass

    async def _serve_fetch(self, args: dict) -> dict:
        """LabVIEW reads the recipe at run start (RECIPE §11), run-params
        substituted before it crosses the bridge (RECIPE §8)."""
        recipe = await self.get_recipe(args["recipe_id"], version=args.get("version"))
        return substitute(recipe, args.get("run_parameters", {}))

    async def health(self) -> Health:
        n = len(step_registry.all_types())
        return Health(status=HealthStatus.OK, detail=f"{n} step types")

    # --- step-type introspection (R1) --------------------------------------

    def list_step_types(self) -> list[dict]:
        return [
            {
                "type_id": rec.type_id,
                "display_name": rec.display_name,
                "composite": rec.composite,
                "capabilities": list(rec.capabilities),
            }
            for rec in step_registry.all_types().values()
        ]

    def get_step_schema(self, type_id: str) -> dict:
        return step_registry.get(type_id).schema

    # --- discovery (R2) ----------------------------------------------------

    async def list_recipes(self, status: str | None = None, tag: str | None = None) -> list[dict]:
        out = []
        for rid in self.store.list_recipe_ids():
            meta = self.store.read_meta(rid)
            if status and meta.get("status") != status:
                continue
            if tag and tag not in meta.get("tags", []):
                continue
            out.append({
                "recipe_id": rid, "name": meta.get("name"), "status": meta.get("status"),
                "latest_version": meta.get("latest_version", 0), "tags": meta.get("tags", []),
                "required_role": meta.get("required_role"),
            })
        return out

    async def list_versions(self, recipe_id: str) -> list[dict]:
        meta = self.store.read_meta(recipe_id)
        archived = set(meta.get("archived_versions", []))
        out = []
        for n in self.store.list_versions(recipe_id):
            r = self.store.read_version(recipe_id, n)
            out.append({"version": n, "content_hash": r.get("content_hash"),
                        "archived": n in archived})
        return out

    async def get_recipe(self, recipe_id: str, version: int | None = None) -> dict:
        meta = self.store.read_meta(recipe_id)
        n = version if version is not None else meta.get("latest_version", 0)
        if not n:
            raise RecipeStoreError(f"'{recipe_id}' has no published version")
        return self.store.read_version(recipe_id, n)

    async def get_by_barcode(self, barcode: str) -> dict:
        for rid in self.store.list_recipe_ids():
            meta = self.store.read_meta(rid)
            if meta.get("status") != "active":
                continue
            if any(barcode.startswith(p) for p in meta.get("barcode_prefixes", [])):
                return await self.get_recipe(rid)
        raise RecipeStoreError(f"no active recipe matches barcode '{barcode}'")

    # --- authoring (R2) ----------------------------------------------------

    async def create_recipe(self, payload: dict) -> dict:
        rid = payload.get("recipe_id")
        if not rid:
            raise RecipeValidationError(["recipe_id required"])
        if self.store.exists(rid):
            raise RecipeExistsError(f"recipe '{rid}' already exists")
        meta = {
            "recipe_id": rid, "name": payload.get("name", rid), "owner": payload.get("owner"),
            "status": "draft", "latest_version": 0, "created_at": _now_iso(),
            "tags": payload.get("tags", []), "barcode_prefixes": payload.get("barcode_prefixes", []),
            "archived_versions": [],
        }
        self.store.write_meta(rid, meta)
        draft_id = self.store.new_draft_id(rid)
        draft = {**payload, "status": "draft", "version": 1}
        self.store.write_draft(rid, draft_id, draft, base_version=None)
        self.core.diag.info("recipe", "recipe created", recipe_id=rid)
        await self._emit_event("recipe-created", {"recipe_id": rid, "by": meta["owner"]})
        return {"recipe_id": rid, "draft_id": draft_id, "recipe": draft}

    async def fork_draft(self, recipe_id: str) -> dict:
        meta = self.store.read_meta(recipe_id)
        base = meta.get("latest_version", 0)
        payload = self.store.read_version(recipe_id, base) if base else {"recipe_id": recipe_id}
        draft_id = self.store.new_draft_id(recipe_id)
        draft = {**payload, "status": "draft"}
        self.store.write_draft(recipe_id, draft_id, draft, base_version=base or None)
        return {"recipe_id": recipe_id, "draft_id": draft_id, "recipe": draft}

    async def save_draft(self, recipe_id: str, draft_id: str, payload: dict) -> dict:
        base = self.store.read_draft_base(recipe_id, draft_id)  # raises later if missing
        self.store.read_draft(recipe_id, draft_id)  # existence (404 if absent)
        draft = {**payload, "status": "draft"}
        self.store.write_draft(recipe_id, draft_id, draft, base_version=base)
        return {"recipe_id": recipe_id, "draft_id": draft_id, "recipe": draft}

    async def publish_draft(self, recipe_id: str, draft_id: str) -> dict:
        meta = self.store.read_meta(recipe_id)
        draft = self.store.read_draft(recipe_id, draft_id)
        n = meta.get("latest_version", 0) + 1
        recipe = {**draft, "version": n, "status": "active"}
        recipe.pop("content_hash", None)
        recipe["content_hash"] = content_hash(recipe)

        report = self.validate(recipe)  # schema + semantic; hard-fail (RECIPE §7)
        if not report["ok"]:
            raise RecipeValidationError(report["errors"])

        self.store.write_version(recipe_id, n, recipe, recipe["content_hash"])
        meta.update({
            "latest_version": n, "status": "active", "name": recipe.get("name", meta["name"]),
            "tags": recipe.get("tags", meta.get("tags", [])),
            "barcode_prefixes": recipe.get("barcode_prefixes", meta.get("barcode_prefixes", [])),
            "required_role": recipe.get("required_role"),
        })
        self.store.write_meta(recipe_id, meta)
        self.store.remove_draft(recipe_id, draft_id)
        await self._mirror_db(recipe_id, n, recipe)
        self.core.diag.info("recipe", "version saved", recipe_id=recipe_id, version=n)
        await self._emit_event("recipe-version-saved",
                               {"recipe_id": recipe_id, "version": n,
                                "content_hash": recipe["content_hash"], "by": recipe.get("owner")})
        return recipe

    async def deprecate(self, recipe_id: str, reason: str = "") -> dict:
        meta = self.store.read_meta(recipe_id)
        meta["status"] = "deprecated"
        self.store.write_meta(recipe_id, meta)
        self.core.diag.info("recipe", "recipe deprecated", recipe_id=recipe_id, reason=reason)
        await self._emit_event("recipe-deprecated", {"recipe_id": recipe_id, "reason": reason})
        return meta

    async def archive(self, recipe_id: str, version: int) -> dict:
        meta = self.store.read_meta(recipe_id)
        if version not in self.store.list_versions(recipe_id):
            raise RecipeStoreError(f"no version v{version} of '{recipe_id}'")
        archived = set(meta.get("archived_versions", []))
        archived.add(version)
        meta["archived_versions"] = sorted(archived)
        self.store.write_meta(recipe_id, meta)
        self.core.diag.info("recipe", "version archived", recipe_id=recipe_id, version=version)
        await self._emit_event("recipe-archived", {"recipe_id": recipe_id, "version": version})
        return meta

    # --- validation (R3) ---------------------------------------------------

    def validate(self, payload: dict, station: str | None = None, strict: bool = False) -> dict:
        """RECIPE §7: schema + semantic (errors, hard-fail) + cross-reference
        (deferred, warn-only). Returns {ok, errors, warnings}."""
        errors = self._schemas.validate_recipe(payload)
        if not errors:  # semantic assumes a well-shaped tree
            errors += check_semantic(payload)
        warnings = check_cross_references(payload)
        return {"ok": not errors, "errors": errors, "warnings": warnings}

    # --- export / import (R5) ----------------------------------------------

    def _source_version(self) -> str:
        return getattr(self.core.db, "source_version", "0.0.0")

    async def export_recipe(self, recipe_id: str, versions: str = "latest") -> bytes:
        self.store.read_meta(recipe_id)  # 404 if absent
        return ei.export_recipe(self.store, recipe_id, versions,
                                station=self.core.station, source_version=self._source_version())

    async def export_all(self) -> bytes:
        return ei.export_all(self.store, station=self.core.station,
                             source_version=self._source_version())

    async def import_bundle(self, data: bytes, mode: str = "add") -> dict:
        report = ei.import_bundle(self.store, data, mode)
        for item in report["imported"]:
            for n in item["versions"]:
                await self._mirror_db(item["recipe_id"], n, self.store.read_version(item["recipe_id"], n))
        if report["imported"]:
            await self._emit_event("recipe-imported", {
                "recipes": [i["recipe_id"] for i in report["imported"]],
                "mode": mode, "conflicts": report["conflicts"],
            })
        self.core.diag.info("recipe", "import", mode=mode,
                            imported=len(report["imported"]), skipped=len(report["skipped"]),
                            conflicts=len(report["conflicts"]))
        return report

    # --- corpus + events ---------------------------------------------------

    async def diff(self, recipe_id: str, from_v: int, to_v: int) -> dict:
        old = self.store.read_version(recipe_id, from_v)
        new = self.store.read_version(recipe_id, to_v)
        return diff_recipes(old, new)

    async def _mirror_db(self, recipe_id: str, n: int, recipe: dict) -> None:
        name = recipe.get("name", recipe_id)
        if n > 1 and (n - 1) in self.store.list_versions(recipe_id):
            d = diff_recipes(self.store.read_version(recipe_id, n - 1), recipe)
            summary = diff_summary(d, n, name)  # RAG hook (RECIPE §9)
        else:
            summary = f"Created v{n} of '{name}'"
        await self.core.db.repo.put("recipe.version", recipe, id=f"{recipe_id}:v{n}", summary=summary)

    async def _emit_event(self, kind: str, payload: dict) -> None:
        bridge = self.core.bridge
        if bridge is not None and getattr(bridge, "connected", False):
            try:
                await bridge.publish(f"event/{kind}", {"type": kind, "ts": time.time(), "payload": payload})
            except Exception:  # noqa: BLE001 — events are best-effort
                pass

"""Recipe export / import (RECIPE.md §10).

ZIP layout (nested by recipe_id so single + all-recipes share one shape):
    <recipe_id>/meta.json
    <recipe_id>/vN/recipe.json (+ .sha256)
    manifest.json   # {exported_at, source_station, source_version, recipes, manifest_hash}

manifest_hash = sha256 over every packed file (sorted by name), excluding
manifest.json itself — corruption detection. Import is warn-only-at-load
(RECIPE §7): recipes are written as-is, never rejected on validation.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

from modules.recipe.storage import RecipeStore
from modules.recipe.versioning import content_hash


def _select_versions(store: RecipeStore, recipe_id: str, spec: str | None) -> list[int]:
    allv = store.list_versions(recipe_id)
    if not allv:
        return []
    if spec in (None, "latest"):
        return [max(allv)]
    if spec == "all":
        return allv
    if isinstance(spec, str) and spec.startswith("range:"):
        a, b = (int(x) for x in spec[6:].split("-"))
        return [v for v in allv if a <= v <= b]
    return allv


def _add(files: dict[str, bytes], name: str, obj) -> None:
    files[name] = json.dumps(obj, indent=2).encode("utf-8")


def _pack(store: RecipeStore, recipe_ids: list[str], spec: str, *, station: str, source_version: str) -> bytes:
    files: dict[str, bytes] = {}
    packed: list[str] = []
    for rid in recipe_ids:
        files[f"{rid}/meta.json"] = json.dumps(store.read_meta(rid), indent=2).encode()
        for n in _select_versions(store, rid, spec):
            recipe = store.read_version(rid, n)
            _add(files, f"{rid}/v{n}/recipe.json", recipe)
            files[f"{rid}/v{n}/recipe.json.sha256"] = (recipe.get("content_hash") or "").encode()
        packed.append(rid)

    h = hashlib.sha256()
    for name in sorted(files):
        h.update(files[name])
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_station": station,
        "source_version": source_version,
        "recipes": packed,
        "manifest_hash": f"sha256:{h.hexdigest()}",
    }
    files["manifest.json"] = json.dumps(manifest, indent=2).encode()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            z.writestr(name, files[name])
    return buf.getvalue()


def export_recipe(store, recipe_id, versions, *, station, source_version) -> bytes:
    return _pack(store, [recipe_id], versions, station=station, source_version=source_version)


def export_all(store, *, station, source_version) -> bytes:
    return _pack(store, store.list_recipe_ids(), "all", station=station, source_version=source_version)


def _incoming(z: zipfile.ZipFile) -> dict[str, list[int]]:
    """recipe_id -> sorted version numbers present in the bundle."""
    out: dict[str, set[int]] = {}
    for name in z.namelist():
        if name == "manifest.json" or name.endswith("/"):
            continue
        parts = name.split("/")
        if len(parts) >= 3 and parts[1].startswith("v") and parts[1][1:].isdigit():
            out.setdefault(parts[0], set()).add(int(parts[1][1:]))
    return {rid: sorted(v) for rid, v in out.items()}


def import_bundle(store: RecipeStore, data: bytes, mode: str = "add") -> dict:
    z = zipfile.ZipFile(io.BytesIO(data))
    incoming = _incoming(z)
    imported: list[dict] = []
    skipped: list[str] = []
    conflicts: list[str] = []

    present = [rid for rid in incoming if store.exists(rid)]
    if mode == "reject_on_conflict" and present:
        return {"imported": [], "skipped": [], "conflicts": sorted(present)}

    for rid, vnums in incoming.items():
        exists = store.exists(rid)
        if mode == "add" and exists:
            skipped.append(rid)
            continue

        if mode == "update" and exists:
            base = store.read_meta(rid).get("latest_version", 0)
            new_versions = []
            for i, n in enumerate(vnums, start=1):
                recipe = json.loads(z.read(f"{rid}/v{n}/recipe.json"))
                nn = base + i
                recipe["version"] = nn
                recipe.pop("content_hash", None)
                recipe["content_hash"] = content_hash(recipe)
                store.write_version(rid, nn, recipe, recipe["content_hash"])
                new_versions.append(nn)
            meta = store.read_meta(rid)
            meta["latest_version"] = base + len(vnums)
            store.write_meta(rid, meta)
            imported.append({"recipe_id": rid, "versions": new_versions})
        else:  # fresh import (new recipe_id)
            meta = json.loads(z.read(f"{rid}/meta.json"))
            for n in vnums:
                recipe = json.loads(z.read(f"{rid}/v{n}/recipe.json"))
                store.write_version(rid, n, recipe, recipe.get("content_hash") or content_hash(recipe))
            meta["latest_version"] = max(vnums) if vnums else 0
            store.write_meta(rid, meta)
            imported.append({"recipe_id": rid, "versions": vnums})

    return {"imported": imported, "skipped": skipped, "conflicts": conflicts}

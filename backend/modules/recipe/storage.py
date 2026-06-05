"""Filesystem recipe store (RECIPE.md §5.3).

Folder-per-recipe: meta.json (only mutable file) + vN/ frozen versions + drafts/.
Pure synchronous filesystem ops; the variant adds async DB mirroring + events.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


class RecipeStoreError(Exception):
    """Recipe/version/draft not found (maps to 404)."""


class RecipeExistsError(RecipeStoreError):
    """Recipe id already exists (maps to 409)."""


class RecipeValidationError(Exception):
    """Recipe failed validation at save/publish (maps to 422)."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class RecipeStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # --- paths -------------------------------------------------------------

    def recipe_dir(self, recipe_id: str) -> Path:
        return self.root / recipe_id

    def _meta_path(self, recipe_id: str) -> Path:
        return self.recipe_dir(recipe_id) / "meta.json"

    def _version_dir(self, recipe_id: str, n: int) -> Path:
        return self.recipe_dir(recipe_id) / f"v{n}"

    def _draft_dir(self, recipe_id: str, draft_id: str) -> Path:
        return self.recipe_dir(recipe_id) / "drafts" / draft_id

    # --- existence / discovery ---------------------------------------------

    def exists(self, recipe_id: str) -> bool:
        return self._meta_path(recipe_id).exists()

    def list_recipe_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(d.name for d in self.root.iterdir() if (d / "meta.json").exists())

    # --- meta --------------------------------------------------------------

    def read_meta(self, recipe_id: str) -> dict:
        p = self._meta_path(recipe_id)
        if not p.exists():
            raise RecipeStoreError(f"no recipe '{recipe_id}'")
        return json.loads(p.read_text(encoding="utf-8"))

    def write_meta(self, recipe_id: str, meta: dict) -> None:
        d = self.recipe_dir(recipe_id)
        d.mkdir(parents=True, exist_ok=True)
        self._meta_path(recipe_id).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # --- versions ----------------------------------------------------------

    def list_versions(self, recipe_id: str) -> list[int]:
        d = self.recipe_dir(recipe_id)
        if not d.exists():
            return []
        out = []
        for child in d.iterdir():
            if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
                out.append(int(child.name[1:]))
        return sorted(out)

    def read_version(self, recipe_id: str, n: int) -> dict:
        p = self._version_dir(recipe_id, n) / "recipe.json"
        if not p.exists():
            raise RecipeStoreError(f"no version v{n} of '{recipe_id}'")
        return json.loads(p.read_text(encoding="utf-8"))

    def write_version(self, recipe_id: str, n: int, recipe: dict, sha: str) -> None:
        vd = self._version_dir(recipe_id, n)
        vd.mkdir(parents=True, exist_ok=True)
        (vd / "recipe.json").write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        (vd / "recipe.json.sha256").write_text(sha, encoding="utf-8")

    # --- drafts ------------------------------------------------------------

    def new_draft_id(self, recipe_id: str) -> str:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        drafts = self.recipe_dir(recipe_id) / "drafts"
        seq = 1 + (len(list(drafts.iterdir())) if drafts.exists() else 0)
        return f"d-{date}-{seq:03d}"

    def write_draft(self, recipe_id: str, draft_id: str, recipe: dict, base_version: int | None) -> None:
        dd = self._draft_dir(recipe_id, draft_id)
        dd.mkdir(parents=True, exist_ok=True)
        (dd / "recipe.json").write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        (dd / "meta.json").write_text(
            json.dumps({"base_version": base_version, "updated_at": time.time()}), encoding="utf-8"
        )

    def read_draft(self, recipe_id: str, draft_id: str) -> dict:
        p = self._draft_dir(recipe_id, draft_id) / "recipe.json"
        if not p.exists():
            raise RecipeStoreError(f"no draft '{draft_id}' of '{recipe_id}'")
        return json.loads(p.read_text(encoding="utf-8"))

    def read_draft_base(self, recipe_id: str, draft_id: str) -> int | None:
        p = self._draft_dir(recipe_id, draft_id) / "meta.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8")).get("base_version")

    def list_drafts(self, recipe_id: str) -> list[str]:
        drafts = self.recipe_dir(recipe_id) / "drafts"
        if not drafts.exists():
            return []
        return sorted(d.name for d in drafts.iterdir() if (d / "recipe.json").exists())

    def remove_draft(self, recipe_id: str, draft_id: str) -> None:
        import shutil

        dd = self._draft_dir(recipe_id, draft_id)
        if dd.exists():
            shutil.rmtree(dd)

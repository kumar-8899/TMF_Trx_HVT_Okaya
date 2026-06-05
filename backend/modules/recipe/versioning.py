"""Content hashing (RECIPE.md §5.1) — sha256 of canonical JSON, immutable per version."""

from __future__ import annotations

import hashlib
import json


def canonical_json(recipe: dict) -> str:
    """Deterministic JSON, excluding the content_hash field itself."""
    body = {k: v for k, v in recipe.items() if k != "content_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(recipe: dict) -> str:
    digest = hashlib.sha256(canonical_json(recipe).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"

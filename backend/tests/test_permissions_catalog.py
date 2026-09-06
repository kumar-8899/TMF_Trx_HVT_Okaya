"""Guard against the exact gap this catches once for real: a route gated on a `DOMAIN.ACTION`
permission that was never added to `modules.auth.permissions_catalog` — invisible to the
Permissions page's role matrix (no role can be granted it there, and an existing wildcard grant
like `DIAGNOSTICS.*` hides that the concrete key isn't independently manageable). Scans every
`require_permission("...")` / `permission_granted(..., "...")` call site under `backend/` and
asserts each literal key is cataloged. Keep this passing when a new module adds a permission —
add it to `permissions_catalog.PERMISSIONS` in the same change."""

import re
from pathlib import Path

from modules.auth.permissions_catalog import KEYS as CATALOG_KEYS

BACKEND = Path(__file__).resolve().parents[1]
_PATTERNS = (
    re.compile(r'require_permission\("([A-Z][A-Z_]*\.[A-Z_]+)"\)'),
    re.compile(r'permission_granted\([^,]+,\s*"([A-Z][A-Z_]*\.[A-Z_]+)"\)'),
)


def _enforced_permission_keys() -> dict[str, list[str]]:
    """literal permission key -> the file(s) that gate a route on it."""
    found: dict[str, list[str]] = {}
    for path in BACKEND.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _PATTERNS:
            for m in pattern.finditer(text):
                found.setdefault(m.group(1), []).append(str(path.relative_to(BACKEND)))
    return found


def test_every_enforced_permission_is_in_the_catalog():
    enforced = _enforced_permission_keys()
    missing = {k: v for k, v in enforced.items() if k not in CATALOG_KEYS}
    assert not missing, (
        "permission(s) gate a route but are missing from modules.auth.permissions_catalog "
        f"(add them there so the Permissions page can manage them): {missing}"
    )


def test_catalog_has_no_duplicate_keys():
    from modules.auth.permissions_catalog import PERMISSIONS
    keys = [p["key"] for p in PERMISSIONS]
    assert len(keys) == len(set(keys)), "duplicate key in permissions_catalog.PERMISSIONS"

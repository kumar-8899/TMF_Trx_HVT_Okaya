"""Known-issues catalog + deterministic signature matching (HEALTH_CHECK.md §7).

The automatic match path is **structured-only and deterministic** (§7.1): a
failure signature is matched against hand-authored issue patterns; most-specific
wins. Free text powers a separate human-driven search (§7.5), never the automatic
key. Catalog entries are JSON files (shipped defaults + a deployer dir), loaded
and validated at init like every other config.
"""

from __future__ import annotations

import json
from pathlib import Path

_WILD = (None, "", "*")
_SIG_KEYS = ("check_id", "instance_family", "error_category", "error_code", "status")


def load_issues(dirs: list[Path]) -> list[dict]:
    issues: list[dict] = []
    for d in dirs:
        if not d or not d.exists():
            continue
        for path in sorted(d.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for entry in (doc if isinstance(doc, list) else [doc]):
                if isinstance(entry, dict) and entry.get("issue_id"):
                    issues.append(entry)
    return issues


def _matches(pattern: dict, sig: dict) -> bool:
    for k, v in (pattern or {}).items():
        if v in _WILD:
            continue
        if sig.get(k) != v:
            return False
    return True


def _specificity(pattern: dict) -> int:
    return sum(1 for k, v in (pattern or {}).items() if k in _SIG_KEYS and v not in _WILD)


def match(sig: dict, issues: list[dict]) -> dict | None:
    """Most-specific matching issue, or None. Ties broken by confidence then order."""
    rank = {"confirmed": 3, "probable": 2, "speculative": 1}
    best, best_key = None, (-1, -1)
    for iss in issues:
        if _matches(iss.get("match", {}), sig):
            key = (_specificity(iss.get("match", {})), rank.get(iss.get("confidence"), 0))
            if key > best_key:
                best, best_key = iss, key
    return best


def search(issues: list[dict], q: str, check_id: str | None = None) -> list[dict]:
    out = issues
    if check_id:
        out = [i for i in out if (i.get("match", {}).get("check_id") in (check_id, None, "*"))]
    if q:
        ql = q.lower()
        def hay(i: dict) -> str:
            r = i.get("remedy", {}) or {}
            return " ".join(str(x) for x in [i.get("issue_id"), i.get("title"), i.get("symptom"),
                                             i.get("cause"), r.get("text")]).lower()
        out = [i for i in out if ql in hay(i)]
    return out

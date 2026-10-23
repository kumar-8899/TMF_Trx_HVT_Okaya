"""Does this tool know the app it is looking at? (`COMPAT.json`, docs/DEBUG_TOOL.md "Version skew")

The tool is released on its own cadence and reads another program's files, so it states what it was tested against. A version
outside that range is never an error - the tool keeps serving what it can understand - but it is reported in `bench_health` and in
the operator Status page, so nobody mistakes "fewer features" for "nothing wrong".
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _tuple(v: str | None) -> tuple[int, ...] | None:
    m = re.match(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?", v or "")
    return tuple(int(x or 0) for x in m.groups()) if m else None


def load(path: Path | None = None) -> dict:
    p = path or Path(__file__).resolve().parent / "COMPAT.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check(framework_version: str | None, compat: dict | None = None) -> dict:
    """-> {status: ok|newer|older|unknown, tested_up_to, note}"""
    c = compat if compat is not None else load()
    fw = c.get("framework") or {}
    got, lo, hi = _tuple(framework_version), _tuple(fw.get("min")), _tuple(fw.get("max_tested"))
    base = {"tool_version": c.get("tool_version"), "tested_up_to": fw.get("max_tested")}
    if got is None:
        return {**base, "status": "unknown", "note": "the app's framework version could not be read (RELEASE.json missing?) - "
                                                    "assuming a compatible layout"}
    if lo and got < lo:
        return {**base, "status": "older", "note": f"framework {framework_version} is older than this tool supports (>= {fw.get('min')}); "
                                                    "some features will be unavailable"}
    if hi and got > hi:
        return {**base, "status": "newer", "note": f"framework {framework_version} is newer than this tool was tested with "
                                                    f"({fw.get('max_tested')}); it still serves what it understands - update the Debug Tool"}
    return {**base, "status": "ok", "note": ""}

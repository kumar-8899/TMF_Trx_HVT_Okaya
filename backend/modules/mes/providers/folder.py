"""Folder MES transport — the classic file-handoff interlock.

Each stage writes `{downstream_dir}/{PASS|FAIL}/{serial}.json`. The next stage's
`upstream_dir` points at the previous stage's downstream dir; a unit may proceed
only if `{upstream_dir}/PASS/{serial}.json` exists.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from core.services.interlock import InterlockResult


def _safe(serial: str) -> str:
    # keep the filename to a barcode-ish token; no path traversal
    return "".join(c for c in serial if c.isalnum() or c in ("-", "_", "."))[:128]


class FolderProvider:
    def __init__(self, config: dict, on_missing: str = "block") -> None:
        self.upstream = Path(config.get("upstream_dir", "")) if config.get("upstream_dir") else None
        self.downstream = Path(config["downstream_dir"]) if config.get("downstream_dir") else None
        self.on_missing = on_missing

    async def check_upstream(self, serial: str) -> InterlockResult:
        if self.upstream is None:
            return InterlockResult(allowed=True, detail="no upstream configured (first stage)")
        name = f"{_safe(serial)}.json"
        if (self.upstream / "PASS" / name).exists():
            return InterlockResult(allowed=True, prior_result="PASS", detail="upstream PASS")
        if (self.upstream / "FAIL" / name).exists():
            return InterlockResult(allowed=False, prior_result="FAIL",
                                   detail="unit failed at the previous stage")
        if self.on_missing == "allow":
            return InterlockResult(allowed=True, detail="no upstream record (allowed by policy)")
        return InterlockResult(allowed=False, detail="no PASS record from the previous stage")

    async def publish_result(self, serial: str, result: str, payload: dict) -> None:
        if self.downstream is None:
            return
        bucket = "PASS" if str(result).upper().startswith("PASS") else "FAIL"
        out = self.downstream / bucket
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{_safe(serial)}.json").write_text(
            json.dumps({**payload, "serial": serial, "result": result,
                        "written_ts": time.time()}, indent=2),
            encoding="utf-8",
        )

    def describe(self) -> dict:
        return {"kind": "folder",
                "upstream_dir": str(self.upstream) if self.upstream else None,
                "downstream_dir": str(self.downstream) if self.downstream else None,
                "on_missing": self.on_missing}

"""Folder report sink — result-routed file drops for MES integration.

Writes {path}/{PASS|FAIL}/{run_id}.{json|csv}. CSV flattens the run + its step
measurements (one row per measurement). Both per-station and config-driven.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from modules.report.assembly import result_is_pass


class FolderSink:
    method_id = "folder"

    def __init__(self, path: str, when: str = "all", fmt: str = "json") -> None:
        self.root = Path(path)
        self.when = when
        self.fmt = fmt

    async def write(self, report: dict) -> None:
        bucket = "PASS" if result_is_pass(report.get("result")) else "FAIL"
        out_dir = self.root / bucket
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{report['run_id']}.{self.fmt}"
        if self.fmt == "csv":
            target.write_text(report_to_csv(report), encoding="utf-8")
        else:
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")


def report_to_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", "serial_no", "result", "recipe_id",
                "test_name", "expected", "measured", "cycle_time_ms"])
    meta = (report.get("run_id"), report.get("serial_no"), report.get("result"), report.get("recipe_id"))
    rows = report.get("rows") or []
    if rows:
        for r in rows:
            w.writerow([*meta, r.get("test_name", ""), r.get("expected", ""),
                        r.get("measured", ""), r.get("cycle_time_ms", "")])
    else:
        # legacy step-measurement fallback
        meas = report.get("measurements", [])
        if not meas:
            w.writerow([*meta, "", "", "", ""])
        for m in meas:
            w.writerow([*meta, m.get("step_id", ""), "", m.get("value", ""), ""])
    return buf.getvalue()

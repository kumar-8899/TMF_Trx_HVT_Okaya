"""Library functions shared by the `tmf-debug` CLI, the TMF Debug Tool and its MCP server.

Pure (no network, no argparse): they operate on captured-record dicts (the shape the sidecar serves,
`CapturedRecord.to_dict()`), so the same logic answers a CLI command, an MCP tool call and an offline bundle
analysis - which is the point of moving it out of `cli.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from tmf_debug.digest import digest_file


def run_id_of(rec: dict) -> str | None:
    """Best-effort run id from a captured record: an explicit run_id anywhere in the
    payload tree, else a `run:*` trace."""
    def dig(v):
        if isinstance(v, dict):
            for key in ("run_id", "runId"):
                if v.get(key):
                    return str(v[key])
            for sub in v.values():
                got = dig(sub)
                if got:
                    return got
        return None

    rid = dig(rec.get("payload"))
    if rid:
        return rid
    trace = rec.get("trace")
    return trace if isinstance(trace, str) and trace.startswith("run") else None


def select_run(records: list[dict], *, run: str | None = None, last: bool = False) -> tuple[list[dict], str]:
    """Return (subset, label). A run is scoped by its TIME WINDOW - every record between
    its run-started and run-finished - so diag/value frames (which carry no run_id) are
    included, not just the events tagged with the run id."""
    target = run
    if target is None and last:
        starts = [r for r in records if r.get("type") == "run-started"]
        if starts:
            target = run_id_of(starts[-1])
        else:
            target = next((rid for rid in reversed([run_id_of(r) for r in records]) if rid), None)
    if target is None:
        return records, "ring"
    t0 = t1 = None
    for r in records:
        rid = run_id_of(r)
        if r.get("type") == "run-started" and rid == target:
            t0 = r.get("ts")
        elif r.get("type") == "run-finished" and rid == target:
            t1 = r.get("ts")
    if t0 is not None:
        hi = t1 if t1 is not None else max((r.get("ts") or 0 for r in records), default=t0)
        return [r for r in records if r.get("ts") is not None and t0 <= r["ts"] <= hi], target
    return [r for r in records if run_id_of(r) == target], target   # fallback: tag match


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def safe_label(label: object) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in str(label))


def why(records: list[dict], *, out_dir: Path, prefix: str, run: str | None = None, last: bool = True) -> dict | None:
    """`tmf-debug why` / MCP `bench_why`: scope to the last (or named) run, write the raw capture and its digest
    under `out_dir`, and return the first fault. None when the records hold no run at all."""
    subset, label = select_run(records, run=run, last=last)
    if not subset:
        return None
    raw = Path(out_dir) / f"{prefix}-{safe_label(label)}.jsonl"
    write_jsonl(raw, subset)
    digest_path = digest_file(raw)
    data = json.loads(digest_path.read_text(encoding="utf-8"))
    return {"run": label, "records": len(subset), "first_fault": data.get("first_fault"),
            "fault_count": len(data.get("faults") or []), "digest_path": str(digest_path), "raw_path": str(raw)}

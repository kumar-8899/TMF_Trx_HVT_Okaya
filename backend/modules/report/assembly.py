"""Assemble a run report from the run_event history (the runs module's records).

Independent of whether the `run` record was written yet — built from the
incrementally-persisted run_event timeline + the finishing event's payload.
"""

from __future__ import annotations


def result_is_pass(result: str | None) -> bool:
    return str(result or "").upper().startswith("PASS")


_ROW_KEYS = ("serial_no", "test_name", "expected", "measured", "result", "cycle_time_ms")


def build_report(run_id: str, events: list[dict], finished: dict, station: str,
                 run_record: dict | None = None) -> dict:
    """Assemble a report from the run_event timeline, enriched by the runs module's
    `run` record (recipe_id / serial_no / model / accumulated test-result rows)."""
    rec = run_record or {}
    started = next((e for e in events if e.get("type") == "run-started"), {})
    recipe_id = rec.get("recipe_id") or started.get("recipe_id") or started.get("recipe")
    recipe_version = rec.get("recipe_version") or started.get("recipe_version") or started.get("version")

    # Legacy step-* events (kept for older sequencers).
    steps: list[dict] = []
    measurements: list[dict] = []
    for e in events:
        if str(e.get("type", "")).startswith("step-"):
            ms = e.get("measurements", []) or []
            steps.append({
                "step_id": e.get("step_id"), "status": e.get("status"),
                "measurements": ms, "elapsed_ms": e.get("elapsed_ms"),
            })
            for m in ms:
                measurements.append({"step_id": e.get("step_id"), **m})

    # Test-result rows: prefer the run record's accumulated results, else the events.
    rows = list(rec.get("results") or [])
    if not rows:
        rows = [{k: e.get(k) for k in _ROW_KEYS if k in e}
                for e in events if e.get("type") == "test-result"]

    result = finished.get("result") or rec.get("result") or "UNKNOWN"
    return {
        "run_id": run_id,
        "serial_no": rec.get("serial_no"),
        "model": rec.get("model"),
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "result": result,
        "started_ts": started.get("ts") or rec.get("started_ts"),
        "finished_ts": finished.get("ts") or rec.get("finished_ts"),
        "station": station,
        "rows": rows,
        "steps": steps,
        "measurements": measurements,
        "summary": f"Run {run_id} {result} ({len(rows) or len(steps)} results)",
    }

"""Assemble a run report from the run_event history (the runs module's records).

Independent of whether the `run` record was written yet — built from the
incrementally-persisted run_event timeline + the finishing event's payload.
"""

from __future__ import annotations


def result_is_pass(result: str | None) -> bool:
    return str(result or "").upper().startswith("PASS")


def build_report(run_id: str, events: list[dict], finished: dict, station: str) -> dict:
    started = next((e for e in events if e.get("type") == "run-started"), {})
    recipe_id = started.get("recipe_id") or started.get("recipe")
    recipe_version = started.get("recipe_version") or started.get("version")

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

    result = finished.get("result") or "UNKNOWN"
    return {
        "run_id": run_id,
        "recipe_id": recipe_id,
        "recipe_version": recipe_version,
        "result": result,
        "started_ts": started.get("ts"),
        "finished_ts": finished.get("ts"),
        "station": station,
        "steps": steps,
        "measurements": measurements,
        "summary": f"Run {run_id} {result} ({len(steps)} steps)",
    }

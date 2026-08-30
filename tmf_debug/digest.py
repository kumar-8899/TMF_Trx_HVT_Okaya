"""The `digest` — condense a raw `.jsonl` capture into a small, self-describing
artifact a model can reason over (REMOTE_DEBUG.md §9).

Pure and offline: operates on a list of captured-record dicts (the shape the sidecar
serves — `CapturedRecord.to_dict()`), with no network and no backend import. The whole
point of the system: a raw capture is tens of MB; the digest targets ≤ 100 KB and
promotes the single most useful field, `first_fault`.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

WARN_PLUS = ("warning", "error", "critical")
ERROR_PLUS = ("error", "critical")
MAX_KB = 100


# --- small accessors -------------------------------------------------------

def _body(rec: dict) -> dict:
    p = rec.get("payload")
    return p if isinstance(p, dict) else {}


def _event_data(rec: dict) -> dict:
    """The inner event payload: envelopes are {type, ts, payload:{...}}."""
    inner = _body(rec).get("payload")
    return inner if isinstance(inner, dict) else {}


def _var_name(rec: dict) -> str | None:
    sub = rec.get("subtopic") or ""
    return sub[len("value/"):] if sub.startswith("value/") else None


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


# --- fault detection (the highest-value analysis) --------------------------

def _faults(records: list[dict]) -> list[dict]:
    faults: list[dict] = []

    # unmatched requests → stuck commands
    reqs: dict[str, dict] = {}
    replied: set[str] = set()
    for r in records:
        cid = r.get("corr_id")
        if not cid:
            continue
        if r.get("kind") == "request":
            reqs.setdefault(cid, r)
        elif r.get("kind") == "reply":
            replied.add(cid)
    max_ts = max((r.get("ts") or 0 for r in records), default=0)
    for cid, r in reqs.items():
        if cid not in replied:
            faults.append({"category": "stuck_command", "ts": r.get("ts"), "corr_id": cid,
                           "req_topic": r.get("topic"), "op": r.get("type"),
                           "elapsed_s": round((max_ts - (r.get("ts") or max_ts)), 3)})

    for r in records:
        kind, level = r.get("kind"), r.get("level")
        if kind == "diag" and level in ERROR_PLUS:
            faults.append({"category": "error_diag", "ts": r.get("ts"),
                           "subsystem": r.get("subsystem"), "level": level,
                           "message": r.get("message"), "context": _body(r).get("context")})
        elif kind == "event":
            t = r.get("type") or ""
            data = _event_data(r)
            if t.startswith("safety"):
                faults.append({"category": "safety_trip", "ts": r.get("ts"), "type": t, "data": data})
            result = str(data.get("result", "")).upper()
            is_fail = (result == "FAIL") or t in ("step-failed", "test-failed")
            if is_fail and t in ("test-result", "step-finished", "step-failed",
                                 "test-failed", "run-finished"):
                faults.append({"category": "step_failure", "ts": r.get("ts"), "type": t,
                               "test_name": data.get("test_name") or data.get("step_id"),
                               "result": result or "FAIL",
                               "measured": data.get("measured", data.get("value")),
                               "limits": data.get("limits")})

    faults.sort(key=lambda f: f.get("ts") or 0)
    return faults


# --- the digest ------------------------------------------------------------

def digest_records(records: list[dict], *, meta: dict | None = None) -> dict:
    meta = meta or {}
    diags = [r for r in records if r.get("kind") == "diag"]
    events = [r for r in records if r.get("kind") == "event"]
    values = [r for r in records if r.get("kind") == "value"]

    faults = _faults(records)
    traces_with_error = {r.get("trace") for r in records
                         if (r.get("kind") == "diag" and r.get("level") in ERROR_PLUS)
                         or r.get("valid") is False}
    traces_with_error.discard(None)

    # --- header (self-describing) ---
    stations = {r.get("station") for r in records if r.get("station")}
    tss = [r.get("ts") for r in records if isinstance(r.get("ts"), (int, float))]
    versions = next((_event_data(r) for r in events), {})
    header = {
        "station": next(iter(stations), None),
        "app_version": meta.get("app_version") or versions.get("app_version"),
        "framework_version": meta.get("framework_version") or versions.get("source_version"),
        "host": meta.get("host"),
        "time_range": [min(tss), max(tss)] if tss else None,
        "source_file": meta.get("source_file"),
        "source_bytes": meta.get("source_bytes"),
        "record_count": len(records),
        "completeness": {
            "dropped": meta.get("dropped", 0),
            "suppressed": meta.get("suppressed", 0),
            "snapshots_suppressed": meta.get("snapshots_suppressed", 0),
        },
    }

    # --- included in full ---
    warnings = [{"ts": r.get("ts"), "subsystem": r.get("subsystem"), "level": r.get("level"),
                 "message": r.get("message"), "trace": r.get("trace"),
                 "context": _body(r).get("context")}
                for r in diags if r.get("level") in WARN_PLUS]
    stuck = [f for f in faults if f["category"] == "stuck_command"]
    violations = [{"ts": r.get("ts"), "topic": r.get("topic"), "type": r.get("type"),
                   "schema_version": r.get("schema_version"), "error": r.get("error")}
                  for r in records if r.get("valid") is False]
    waterfalls = {tr: [_trim(r) for r in records if r.get("trace") == tr]
                  for tr in sorted(traces_with_error)}

    # --- summarised, not included ---
    info_debug = Counter((r.get("subsystem"), r.get("message"))
                         for r in diags if r.get("level") in ("debug", "info"))
    analog: dict[str, dict] = {}
    digital: dict[str, int] = defaultdict(int)
    last_bool: dict[str, Any] = {}
    for r in values:
        name = _var_name(r)
        if not name:
            continue
        v = _body(r).get("value")
        n = _num(v)
        if n is not None:
            a = analog.setdefault(name, {"min": n, "max": n, "sum": 0.0, "n": 0})
            a["min"] = min(a["min"], n)
            a["max"] = max(a["max"], n)
            a["sum"] += n
            a["n"] += 1
        else:  # boolean/discrete → count transitions
            if name in last_bool and last_bool[name] != v:
                digital[name] += 1
            last_bool[name] = v
    analog_summary = {k: {"min": a["min"], "max": a["max"],
                          "avg": round(a["sum"] / a["n"], 4) if a["n"] else None, "n": a["n"]}
                      for k, a in analog.items()}

    digest = {
        **{"schema": "tmf-debug/digest/1"},
        "header": header,
        "first_fault": faults[0] if faults else None,
        "faults": faults,
        "warnings": warnings,
        "stuck_commands": stuck,
        "schema_violations": violations,
        "error_trace_waterfalls": waterfalls,
        "snapshot_index": meta.get("snapshots", []),
        "summary": {
            "info_debug_by_subsystem_message": [
                {"subsystem": k[0], "message": k[1], "count": c}
                for k, c in info_debug.most_common()],
            "analog": analog_summary,
            "digital_transitions": dict(digital),
            "by_kind": dict(Counter(r.get("kind") for r in records)),
        },
    }
    return digest


def _trim(rec: dict) -> dict:
    """A record trimmed to the fields that carry meaning in a waterfall."""
    return {k: rec.get(k) for k in ("ts", "kind", "subtopic", "type", "subsystem",
                                    "level", "message", "corr_id") if rec.get(k) is not None}


# --- file entrypoint -------------------------------------------------------

def digest_file(path: Path) -> Path:
    """Read a `.jsonl` capture, write `<file>.digest.json` beside it, return that path."""
    path = Path(path)
    records: list[dict] = []
    meta: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        # a trailing {"__meta__": {...}} line may carry completeness/versions
        if isinstance(obj, dict) and "__meta__" in obj:
            meta.update(obj["__meta__"])
            continue
        records.append(obj)
    meta.setdefault("source_file", path.name)
    meta.setdefault("source_bytes", path.stat().st_size)
    result = digest_records(records, meta=meta)

    text = json.dumps(result, indent=2)
    if len(text.encode("utf-8")) > MAX_KB * 1024:
        result["header"]["oversized"] = (
            f"digest exceeds {MAX_KB} KB — tighten the window with --since / --run / --module")
        text = json.dumps(result, indent=2)
    out = path.parent / (path.stem + ".digest.json")
    out.write_text(text, encoding="utf-8")
    return out

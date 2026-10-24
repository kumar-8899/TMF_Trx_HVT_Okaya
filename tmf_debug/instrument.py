"""Passive instrument history from captured records (no command is ever sent to a device).

Every instrument command/state change is a `diag` event with subsystem "instrument" and a context built by
instrumentlib (`_emit_command` / `_emit_state`): `instance_id`, `method`, `args`, `elapsed_ms`, `outcome`,
`error{type,message,cause,traceback_tail}`, `state`. This turns those into the table a developer actually wants:
state timeline, per-method call/failure counts and latency, and the last failures with their cause.

COVERAGE (stated in every result, because it changes what the numbers mean): under a supervised Python controller
the controller publishes only FAILED commands and unhealthy link states (successes would flood the broker -
`controller/serve.py instrument_diag_sink`), so call counts and latency cover failures plus whatever the backend
itself executed (e.g. Test Bench calls); under a direct (LabVIEW-controller) setup the backend emits every command.
"""

from __future__ import annotations

import re
from collections import defaultdict

BAD_STATES = ("disconnected", "reconnecting", "faulted")
_ID_RE = re.compile(r"^([A-Za-z0-9_\-]+?)(?:\.| link )")


def _ctx(rec: dict) -> dict:
    p = rec.get("payload")
    c = p.get("context") if isinstance(p, dict) else None
    return c if isinstance(c, dict) else {}


def _instance_id(rec: dict, ctx: dict) -> str | None:
    iid = ctx.get("instance_id")
    if iid:
        return str(iid)
    m = _ID_RE.match(rec.get("message") or "")
    return m.group(1) if m else None


def _pct(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return round(sorted_vals[i], 2)


def instrument_digest(records: list[dict], *, instance_id: str | None = None, max_failures: int = 10) -> dict:
    per: dict[str, dict] = defaultdict(lambda: {"timeline": [], "methods": defaultdict(lambda: {"n": 0, "failed": 0, "lat": []}),
                                                "failures": [], "last_ts": None, "last_failure_ts": None})
    tss = [r["ts"] for r in records if isinstance(r.get("ts"), (int, float))]
    seen = 0
    for rec in records:
        if rec.get("subsystem") != "instrument":
            continue
        ctx = _ctx(rec)
        iid = _instance_id(rec, ctx)
        if not iid or (instance_id and iid != instance_id):
            continue
        seen += 1
        ts = rec.get("ts")
        d = per[iid]
        d["last_ts"] = ts if ts is not None else d["last_ts"]
        state = ctx.get("state")
        if state is None and " link " in (rec.get("message") or ""):
            state = (rec.get("message") or "").rsplit(" link ", 1)[-1].strip() or None
        if state:
            if not d["timeline"] or d["timeline"][-1]["state"] != state:
                d["timeline"].append({"ts": ts, "state": state, "level": rec.get("level")})
            continue
        method = ctx.get("method")
        if not method:
            continue
        m = d["methods"][method]
        m["n"] += 1
        if isinstance(ctx.get("elapsed_ms"), (int, float)):
            m["lat"].append(float(ctx["elapsed_ms"]))
        outcome = ctx.get("outcome")
        if outcome not in (None, "ok"):
            m["failed"] += 1
            d["last_failure_ts"] = ts
            err = ctx.get("error") or {}
            d["failures"].append({"ts": ts, "method": method, "outcome": outcome, "args": ctx.get("args"),
                                  "message": err.get("message") or rec.get("message"), "type": err.get("type") or err.get("code"),
                                  "cause": err.get("cause"), "traceback_tail": err.get("traceback_tail"),
                                  "trace": rec.get("trace")})
    out = {}
    for iid, d in sorted(per.items()):
        methods = {}
        for name, m in sorted(d["methods"].items()):
            lat = sorted(m["lat"])
            methods[name] = {"calls": m["n"], "failed": m["failed"],
                             "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "max": round(lat[-1], 2) if lat else None}}
        tl = d["timeline"]
        out[iid] = {
            "state": tl[-1]["state"] if tl else None,
            "state_timeline": tl,
            "drops": sum(1 for t in tl if t["state"] in BAD_STATES),
            "methods": methods,
            "calls": sum(v["calls"] for v in methods.values()),
            "failed_calls": sum(v["failed"] for v in methods.values()),
            "last_event_ts": d["last_ts"],
            "last_failure_ts": d["last_failure_ts"],
            "recent_failures": d["failures"][-max_failures:],
        }
    return {
        "schema": "tmf-debug/instrument/1",
        "time_range": [min(tss), max(tss)] if tss else None,
        "instrument_events": seen,
        "instruments": out,
        "coverage": ("Failed commands and unhealthy link-state changes are always published; successful commands only when the "
                     "backend itself executed them. Counts and latency therefore under-report successes on a Python-controller "
                     "station - use them to find problems, not to compute a success rate."),
    }

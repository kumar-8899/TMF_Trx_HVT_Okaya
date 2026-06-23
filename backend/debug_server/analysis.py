"""Derived signals over the capture (DEBUG_SERVER.md §5).

Trace grouping (§5.2), request/reply pairing + orphan detection (§5.3), schema
validation (§5.5), and liveness from retained status/LWT (§5.4). Pure functions /
small stateful trackers over CapturedRecords — no broker, no I/O.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from debug_server.capture import DIAG, EVENT, REPLY, REQUEST, STATUS, CapturedRecord

_BAD_LEVELS = {"error", "critical"}

# --- §5.5 schema validation -------------------------------------------------
# Validate the two enveloped, body-agnostic shapes the bus guarantees. Matched
# loosely (type + presence); full per-type schemas can be added as the core grows.
_DIAG_REQUIRED = ("ts", "level", "subsystem", "message")
_EVENT_REQUIRED = ("type", "ts")


def validate(rec: CapturedRecord) -> None:
    """Set rec.valid / rec.error for enveloped messages; leave others unchecked."""
    if rec.kind not in (EVENT, DIAG):
        return
    if not isinstance(rec.payload, dict):
        rec.valid, rec.error = False, "payload is not a JSON object"
        return
    required = _DIAG_REQUIRED if rec.kind == DIAG else _EVENT_REQUIRED
    missing = [k for k in required if k not in rec.payload]
    if missing:
        rec.valid, rec.error = False, f"missing field(s): {', '.join(missing)}"
    elif rec.kind == DIAG and rec.payload.get("level") not in (
            "debug", "info", "warning", "error", "critical"):
        rec.valid, rec.error = False, f"bad level: {rec.payload.get('level')!r}"
    else:
        rec.valid = True


# --- §5.3 request / reply pairing ------------------------------------------

@dataclass
class _Req:
    corr_id: str
    req_topic: str
    reply_topic: str | None
    sent_ts: float
    reply_ts: float | None = None
    latency_ms: float | None = None

    @property
    def status(self) -> str:
        return "paired" if self.reply_ts is not None else "pending"


class Pairer:
    def __init__(self, orphan_timeout_s: float = 5.0) -> None:
        self.timeout = orphan_timeout_s
        self._reqs: dict[str, _Req] = {}

    def observe(self, rec: CapturedRecord) -> None:
        if rec.corr_id is None:
            return
        if rec.kind == REQUEST:
            rt = rec.payload.get("reply_to") if isinstance(rec.payload, dict) else None
            self._reqs[rec.corr_id] = _Req(rec.corr_id, rec.subtopic, rt, rec.ts)
        elif rec.kind == REPLY:
            req = self._reqs.get(rec.corr_id)
            if req and req.reply_ts is None:
                req.reply_ts = rec.ts
                req.latency_ms = round((rec.ts - req.sent_ts) * 1000, 2)

    def list(self, *, status: str | None = None, now: float | None = None) -> list[dict]:
        now = now or time.time()
        out = []
        for r in self._reqs.values():
            st = r.status
            if st == "pending" and (now - r.sent_ts) > self.timeout:
                st = "orphan"   # §5.3 no reply within deadline
            if status and st != status:
                continue
            out.append({"corr_id": r.corr_id, "req_topic": r.req_topic,
                        "reply_topic": r.reply_topic, "sent_ts": r.sent_ts,
                        "reply_ts": r.reply_ts, "latency_ms": r.latency_ms, "status": st})
        out.sort(key=lambda x: x["sent_ts"])
        return out


# --- §5.2 trace grouping ----------------------------------------------------

def group_traces(records: list[CapturedRecord]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in records:
        if not r.trace:
            continue
        g = groups.setdefault(r.trace, {"trace": r.trace, "first_ts": r.ts,
                                        "last_ts": r.ts, "count": 0, "has_error": False})
        g["count"] += 1
        g["first_ts"] = min(g["first_ts"], r.ts)
        g["last_ts"] = max(g["last_ts"], r.ts)
        if r.level in _BAD_LEVELS or (r.type or "").endswith(("fail", "failed", "aborted")):
            g["has_error"] = True
    return sorted(groups.values(), key=lambda g: g["first_ts"])


# --- §5.4 liveness from retained status + LWT -------------------------------

class Liveness:
    def __init__(self) -> None:
        self._clients: dict[str, dict] = {}

    def observe(self, rec: CapturedRecord) -> None:
        if rec.kind != STATUS:
            return
        client = rec.subtopic  # e.g. "status" (the controller link)
        state = rec.payload.get("state") if isinstance(rec.payload, dict) else None
        online = state == "online"
        prev = self._clients.get(client)
        lwt = bool(prev and prev["online"] and not online)  # online → offline flip
        self._clients[client] = {"client": client, "status": state or ("online" if online else "offline"),
                                 "online": online, "last_seen": rec.ts,
                                 "lwt_fired": lwt or (prev or {}).get("lwt_fired", False)}

    def grid(self) -> list[dict]:
        return sorted(self._clients.values(), key=lambda c: c["client"])

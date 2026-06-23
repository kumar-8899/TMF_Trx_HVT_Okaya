"""Capture model + ring buffer (DEBUG_SERVER.md §6).

Classifies a bus message into a CapturedRecord and holds the last N losslessly
in a bounded in-memory ring with a drop counter. No disk (§6).
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

# Capture-set topic kinds (§0). stream/# is never captured (not subscribed).
EVENT, DIAG, VALUE, STATUS, REQUEST, REPLY, OTHER = (
    "event", "diag", "value", "status", "request", "reply", "other")


@dataclass
class CapturedRecord:
    seq: int                       # capture-monotonic (assigned by the ring)
    ts: float                      # message ts (envelope) or receive time
    recv_ts: float
    topic: str                     # full topic
    subtopic: str                  # topic minus tmf/<station>/
    kind: str
    station: str
    type: str | None = None        # envelope `type` (event/#)
    subsystem: str | None = None   # diag subsystem
    level: str | None = None       # diag level
    message: str | None = None     # diag message
    trace: str | None = None       # §4 correlation
    corr_id: str | None = None     # request/reply id
    schema_version: int | None = None
    payload: Any = None
    valid: bool | None = None      # schema validation (§5.5); None = not checked
    error: str | None = None       # validation error text

    def to_dict(self) -> dict:
        return asdict(self)


def _kind(subtopic: str) -> str:
    if subtopic.startswith("event/"):
        return EVENT
    if subtopic == "diag" or subtopic.startswith("diag/"):
        return DIAG
    if subtopic.startswith("value/"):
        return VALUE
    if subtopic == "status":
        return STATUS
    if subtopic.startswith("cmd/resp/"):
        return REPLY
    if subtopic.startswith("cmd/"):
        return REQUEST
    return OTHER


def parse(topic: str, station: str, raw: bytes | str) -> CapturedRecord:
    """Build a CapturedRecord from a raw bus message. Bodies are best-effort
    JSON; non-JSON payloads are kept as a string so nothing is dropped."""
    prefix = f"tmf/{station}/"
    subtopic = topic[len(prefix):] if topic.startswith(prefix) else topic
    kind = _kind(subtopic)
    now = time.time()
    try:
        payload = json.loads(raw) if raw not in (b"", "", None) else None
    except (json.JSONDecodeError, TypeError):
        payload = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)

    rec = CapturedRecord(seq=0, ts=now, recv_ts=now, topic=topic, subtopic=subtopic,
                         kind=kind, station=station, payload=payload)
    if isinstance(payload, dict):
        rec.ts = float(payload.get("ts", now))
        rec.trace = payload.get("trace")
        rec.schema_version = payload.get("schema_version")
        if kind == EVENT:
            rec.type = payload.get("type")
        elif kind == DIAG:
            rec.subsystem = payload.get("subsystem")
            rec.level = payload.get("level")
            rec.message = payload.get("message")
            rec.type = "diag"
        elif kind in (REQUEST, REPLY):
            rec.corr_id = payload.get("id")
            rec.type = payload.get("op")
    return rec


class Ring:
    """Bounded, append-only, lossless-within-window capture (§6)."""

    def __init__(self, capacity: int = 50_000) -> None:
        self.capacity = capacity
        self._buf: deque[CapturedRecord] = deque(maxlen=capacity)
        self._seq = 0
        self.dropped = 0

    def add(self, rec: CapturedRecord) -> CapturedRecord:
        self._seq += 1
        rec.seq = self._seq
        if len(self._buf) == self.capacity:
            self.dropped += 1   # oldest about to be evicted
        self._buf.append(rec)
        return rec

    def all(self) -> list[CapturedRecord]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    def query(self, *, since=None, level=None, subsystem=None, topic=None,
              trace=None, kind=None, text=None, limit=500) -> list[CapturedRecord]:
        order = ("debug", "info", "warning", "error", "critical")
        min_lv = order.index(level) if level in order else None
        out = []
        for r in self._buf:
            if since is not None and r.seq <= since:
                continue
            if min_lv is not None and (r.level not in order or order.index(r.level) < min_lv):
                continue
            if subsystem and r.subsystem != subsystem:
                continue
            if kind and r.kind != kind:
                continue
            if topic and not r.subtopic.startswith(topic):
                continue
            if trace and r.trace != trace:
                continue
            if text and text.lower() not in json.dumps(r.payload).lower():
                continue
            out.append(r)
        return out[-limit:] if limit else out

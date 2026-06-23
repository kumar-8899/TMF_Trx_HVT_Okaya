"""Ingestor — the capture pipeline + WS fan-out + capture sessions/export.

Ties the ring, pairer, validator, and liveness together and exposes the derived
views the REST/WS surface serves. Export uses the RAG envelope shape so a capture
drops into the Health corpus with no translation (§5.6 / §9.1).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from debug_server import __version__
from debug_server.analysis import Liveness, Pairer, group_traces, validate
from debug_server.capture import CapturedRecord, Ring


class Ingestor:
    def __init__(self, station: str, *, capacity: int = 50_000, orphan_timeout_s: float = 5.0) -> None:
        self.station = station
        self.ring = Ring(capacity)
        self.pairer = Pairer(orphan_timeout_s)
        self.liveness = Liveness()
        self.broker_connected = False
        self._subs: set[asyncio.Queue] = set()
        self._captures: dict[str, dict] = {}

    # --- pipeline ----------------------------------------------------------

    def ingest(self, rec: CapturedRecord) -> CapturedRecord:
        validate(rec)
        self.ring.add(rec)
        self.pairer.observe(rec)
        self.liveness.observe(rec)
        self._fan_out(rec)
        return rec

    def _fan_out(self, rec: CapturedRecord) -> None:
        dead = []
        for q in self._subs:
            try:
                q.put_nowait(rec)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subs.discard(q)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    # --- derived views -----------------------------------------------------

    def health(self) -> dict:
        return {"buffer_used": len(self.ring), "buffer_capacity": self.ring.capacity,
                "dropped": self.ring.dropped, "subscribers": len(self._subs),
                "broker_connected": self.broker_connected, "station": self.station}

    def traces(self) -> list[dict]:
        return group_traces(self.ring.all())

    def trace(self, trace: str) -> list[dict]:
        return [r.to_dict() for r in self.ring.all() if r.trace == trace]

    def requests(self, status: str | None = None) -> list[dict]:
        return self.pairer.list(status=status)

    def liveness_grid(self) -> list[dict]:
        return self.liveness.grid()

    def violations(self) -> list[dict]:
        return [{"ts": r.ts, "topic": r.topic, "type": r.type,
                 "schema_version": r.schema_version, "error": r.error}
                for r in self.ring.all() if r.valid is False]

    # --- capture sessions + export (§5.6) ----------------------------------

    def capture_start(self, name: str) -> str:
        cid = uuid.uuid4().hex
        self._captures[cid] = {"name": name, "start_seq": self.ring._seq, "stop_seq": None}
        return cid

    def capture_stop(self, cid: str) -> int:
        cap = self._captures.get(cid)
        if cap is None:
            return -1
        cap["stop_seq"] = self.ring._seq
        return cap["stop_seq"] - cap["start_seq"]

    def export_jsonl(self, cid: str) -> str | None:
        cap = self._captures.get(cid)
        if cap is None:
            return None
        lo, hi = cap["start_seq"], cap["stop_seq"] or self.ring._seq
        lines = []
        for r in self.ring.all():
            if lo < r.seq <= hi:
                lines.append(json.dumps(self._envelope(cap["name"], r)))
        return "\n".join(lines) + ("\n" if lines else "")

    def _envelope(self, capture: str, r: CapturedRecord) -> dict:
        # RAG envelope (core/schemas/envelope.schema.json) — Health-ingestable.
        return {"id": f"{capture}:{r.seq}", "type": r.type or r.kind, "ts": r.ts,
                "station": r.station, "source_version": f"debug_server/{__version__}",
                "summary": r.message or r.type or r.kind, "data": r.to_dict()}

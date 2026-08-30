"""Ingestor — the capture pipeline + WS fan-out + capture sessions/export.

Ties the ring, pairer, validator, and liveness together and exposes the derived
views the REST/WS surface serves. Export uses the RAG envelope shape so a capture
drops into the Health corpus with no translation (§5.6 / §9.1).
"""

from __future__ import annotations

import asyncio
import json
import uuid

from debug_server import __version__
from debug_server.analysis import Liveness, Pairer, group_traces, validate
from debug_server.capture import EVENT, STATUS, VALUE, CapturedRecord, Ring


_RUN_START = "run-started"
_RUN_END = ("run-finished", "run-aborted")


class Ingestor:
    def __init__(self, station: str, *, capacity: int = 50_000, orphan_timeout_s: float = 5.0,
                 rolling=None, snapshot=None) -> None:
        self.station = station
        self.ring = Ring(capacity)
        self.pairer = Pairer(orphan_timeout_s)
        self.liveness = Liveness()
        self.broker_connected = False
        self._subs: set[asyncio.Queue] = set()
        self._captures: dict[str, dict] = {}
        self._last_retained: dict[str, str] = {}   # topic -> last payload (dedupe)
        self.coalesced = 0                          # suppressed retained repeats
        self.rolling = rolling                      # RollingSink | None (PR-C)
        self.snapshot = snapshot                    # SnapshotBuffer | None (PR-E)
        self.discipline = None                      # LogDiscipline | None (PR-D)
        self._active = False                        # a run is in progress
        self.app_version: str | None = None
        self.framework_version: str | None = None

    # --- pipeline ----------------------------------------------------------

    def ingest(self, rec: CapturedRecord) -> CapturedRecord:
        # Retained status/value republish on a timer (e.g. LabVIEW status every 1s).
        # Coalesce identical repeats: keep liveness fresh but don't flood the ring.
        if rec.kind in (STATUS, VALUE):
            body = rec.payload
            if isinstance(body, dict):   # ignore volatile stamps so a re-publish dedupes
                body = {k: v for k, v in body.items() if k not in ("ts", "seq")}
            key = json.dumps(body, sort_keys=True, default=str)
            if self._last_retained.get(rec.topic) == key:
                self.coalesced += 1
                if rec.kind == STATUS:
                    self.liveness.observe(rec)   # advance last_seen without a ring entry
                return rec
            self._last_retained[rec.topic] = key
        validate(rec)
        self.ring.add(rec)
        self.pairer.observe(rec)
        self.liveness.observe(rec)
        self._track_run(rec)
        if self.snapshot is not None:
            self.snapshot.observe(rec)            # 30 s values-only buffer (PR-E)
        # To disk: the discipline gates value/# + suppresses repeats (keeps disk bounded);
        # with no discipline, records go raw to the rolling sink. Either path is
        # non-blocking (drop-and-count) — never disk I/O on this call (§5).
        if self.discipline is not None:
            self.discipline.feed(rec.to_dict(), active=self._active)
        elif self.rolling is not None:
            self.rolling.enqueue(rec.to_dict())
        self._fan_out(rec)
        return rec

    def _track_run(self, rec: CapturedRecord) -> None:
        """Toggle run-active state (rolling compression is deferred during a run) and
        learn the app/framework versions from a run-started event for /debug/health."""
        if rec.kind != EVENT:
            return
        if rec.type == _RUN_START:
            body = rec.payload.get("payload", {}) if isinstance(rec.payload, dict) else {}
            self.app_version = body.get("app_version") or self.app_version
            self.framework_version = body.get("source_version") or self.framework_version
            self._active = True
            if self.rolling is not None:
                self.rolling.set_active_run(True)
        elif rec.type in _RUN_END:
            self._active = False
            if self.rolling is not None:
                self.rolling.set_active_run(False)

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
        h = {"buffer_used": len(self.ring), "buffer_capacity": self.ring.capacity,
             "dropped": self.ring.dropped, "coalesced": self.coalesced,
             "subscribers": len(self._subs),
             "broker_connected": self.broker_connected, "station": self.station,
             "app_version": self.app_version, "framework_version": self.framework_version,
             "suppressed": self.discipline.suppressed if self.discipline else 0,
             "snapshots_suppressed": self.snapshot.suppressed if self.snapshot else 0}
        if self.rolling is not None:
            h.update(self.rolling.metrics())
        return h

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

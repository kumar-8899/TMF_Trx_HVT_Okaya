"""Snapshot buffer (REMOTE_DEBUG.md §3.4) — the 30 s of full detail around a failure.

Holds the last `pre_seconds` of **variable VALUES ONLY** in memory (raw stream/# is
never buffered). On any of the four triggers — step failure, an error-level diag, a
safety trip, or a stuck command — it flushes the buffer plus a `post_seconds` tail to
`snapshot-<ts>.jsonl` beside the rolling file, encoded as **compact arrays, never
per-sample records**. Warnings never trigger. Flushes are capped per hour; suppressed
flushes are counted and reported honestly (§5).
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

_HOUR = 3600.0


class SnapshotBuffer:
    def __init__(self, cfg, directory: Path, *, clock=time.time) -> None:
        self.cfg = cfg
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._buf: dict[str, deque] = defaultdict(deque)   # name -> deque[(ts, value)]
        self._pending: dict | None = None
        self._flush_times: deque = deque()
        self.suppressed = 0                                # snapshots_suppressed (§5)
        self._sync = False                                 # tests: write inline, not threaded

    # --- intake ------------------------------------------------------------

    def observe(self, rec) -> None:
        ts = rec.ts or self._clock()
        if rec.kind == "value" and not self.cfg.include_streams:
            name = self._var_name(rec)
            if name is not None:
                val = rec.payload.get("value") if isinstance(rec.payload, dict) else rec.payload
                dq = self._buf[name]
                dq.append((ts, val))
                cutoff = ts - self.cfg.pre_seconds
                while dq and dq[0][0] < cutoff:
                    dq.popleft()
        # flush a pending snapshot once its post-tail window has elapsed
        if self._pending is not None and ts >= self._pending["deadline"]:
            self._flush(self._pending, upto=ts)
            self._pending = None
        reason = self._trigger(rec)
        if reason and self._pending is None:
            self._arm(reason, ts, rec)

    def trigger_stuck(self, corr_id: str, ts: float | None = None) -> None:
        """A stuck command (orphaned request) — the fourth trigger, driven by the pairer."""
        ts = ts or self._clock()
        if self._pending is None:
            self._arm(f"stuck_command:{corr_id}", ts, None)

    def flush_due(self, now: float | None = None) -> None:
        now = now or self._clock()
        if self._pending is not None and now >= self._pending["deadline"]:
            self._flush(self._pending, upto=now)
            self._pending = None

    @staticmethod
    def _var_name(rec) -> str | None:
        sub = rec.subtopic or ""
        return sub[len("value/"):] if sub.startswith("value/") else None

    # --- triggers (exhaustive; warnings never trigger) ---------------------

    @staticmethod
    def _trigger(rec) -> str | None:
        if rec.kind == "diag" and rec.level in ("error", "critical"):
            return f"error:{rec.subsystem}"
        if rec.kind == "event":
            t = rec.type or ""
            if t.startswith("safety"):
                return f"safety:{t}"
            data = rec.payload.get("payload", {}) if isinstance(rec.payload, dict) else {}
            if str(data.get("result", "")).upper() == "FAIL" or t in ("step-failed", "test-failed"):
                return f"step_failure:{data.get('test_name') or t}"
        return None

    def _arm(self, reason: str, ts: float, rec) -> None:
        cutoff = ts - _HOUR
        while self._flush_times and self._flush_times[0] < cutoff:
            self._flush_times.popleft()
        if len(self._flush_times) >= self.cfg.max_per_hour:
            self.suppressed += 1   # a station failing every unit must not flood the disk
            return
        self._pending = {"reason": reason, "trigger_ts": ts,
                         "deadline": ts + self.cfg.post_seconds, "run_id": self._run_id(rec)}

    # --- flush (compact arrays, off the ingest task) -----------------------

    def _flush(self, pending: dict, *, upto: float) -> Path:
        self._flush_times.append(pending["trigger_ts"])
        lo = pending["trigger_ts"] - self.cfg.pre_seconds
        # copy the windowed points now (the ingest task keeps mutating the buffers)
        data = {name: [(t, v) for (t, v) in dq if lo <= t <= upto]
                for name, dq in self._buf.items()}
        data = {k: v for k, v in data.items() if v}
        sid = str(int(pending["trigger_ts"] * 1000))
        path = self.dir / f"snapshot-{sid}.jsonl"
        if self._sync:
            self._write(path, sid, pending, data)
        else:
            threading.Thread(target=self._write, args=(path, sid, pending, data), daemon=True).start()
        return path

    def _write(self, path: Path, sid: str, pending: dict, data: dict) -> None:
        lines = [json.dumps({"__snapshot__": {
            "id": sid, "trigger": pending["reason"], "trigger_ts": pending["trigger_ts"],
            "run_id": pending["run_id"], "snapshots_suppressed": self.suppressed}})]
        for name, pts in data.items():
            t0 = pts[0][0]
            lines.append(json.dumps({"var": name, "t0": round(t0, 4),
                                     "ts": [round(t - t0, 4) for (t, _) in pts],
                                     "v": [v for (_, v) in pts]}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- read-back (feeds /debug/snapshots) --------------------------------

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.dir.glob("snapshot-*.jsonl")):
            meta = {}
            if p.stat().st_size:
                first = p.read_text(encoding="utf-8").splitlines()[0]
                meta = json.loads(first).get("__snapshot__", {})
            out.append({"id": meta.get("id", p.stem), "ts": meta.get("trigger_ts"),
                        "trigger": meta.get("trigger"), "run_id": meta.get("run_id"),
                        "bytes": p.stat().st_size})
        return out

    def read(self, sid: str) -> str | None:
        p = self.dir / f"snapshot-{sid}.jsonl"
        return p.read_text(encoding="utf-8") if p.exists() else None

    @staticmethod
    def _run_id(rec) -> str | None:
        if rec is None or not isinstance(rec.payload, dict):
            return None

        def dig(v):
            if isinstance(v, dict):
                if v.get("run_id"):
                    return str(v["run_id"])
                for sub in v.values():
                    got = dig(sub)
                    if got:
                        return got
            return None
        return dig(rec.payload)

"""Rolling JSONL sink (REMOTE_DEBUG.md §3.3 / §4 / §5) — the evidence that survives
an unattended fault when no client was connected.

The performance contract is normative and enforced by construction (§5/§13.4):
- `enqueue()` pushes to a bounded in-memory queue and returns — **it never touches
  disk on the calling thread.**
- When the queue is full it **drops and counts**, never blocks. Losing log lines is
  acceptable; delaying a test step is not. Drops are reported honestly.
- A background writer drains the queue, appends one JSON object per line, rotates at
  a size cap, gzips rotated files **on the writer at low priority, never during an
  active run**, and evicts oldest when the total exceeds the cap. The **size cap is
  authoritative**; `retention_days` is an additional constraint.
"""

from __future__ import annotations

import gzip
import json
import queue
import shutil
import threading
import time
from pathlib import Path

from debug_server.config import RollingConfig

_MB = 1024 * 1024


class RollingSink:
    def __init__(self, cfg: RollingConfig, directory: Path, *, queue_size: int = 20_000,
                 clock=time.time) -> None:
        self.cfg = cfg
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._q: queue.Queue = queue.Queue(maxsize=queue_size)
        self.dropped = 0
        self._active_run = False
        self._pending_gz: list[Path] = []
        self._fh = None
        self._cur = self.dir / "debug.jsonl"
        self._bytes_today = 0
        self._day = self._today()
        self._run_bytes = 0
        self._run_samples: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Size thresholds (bytes). Tests may override with tiny values.
        self._file_cap = cfg.max_file_mb * _MB
        self._total_cap = cfg.max_total_mb * _MB

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self.cfg.enabled and self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="debug-rolling", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._drain_once(block=False)   # flush whatever remains
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def set_active_run(self, active: bool) -> None:
        """Track run boundaries so compression never runs mid-test and per-run byte
        totals can be reported."""
        was = self._active_run
        self._active_run = active
        if not was and active:
            self._run_bytes = 0
        elif was and not active:
            self._run_samples.append(self._run_bytes)
            self._compress_pending()   # run ended → safe to gzip deferred rotations

    # --- calling-thread side (NEVER touches disk) --------------------------

    def enqueue(self, record: dict) -> None:
        if not self.cfg.enabled:
            return
        try:
            self._q.put_nowait(record)
        except queue.Full:
            self.dropped += 1   # drop-and-count, never block (§13.4)

    # --- writer side -------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._drain_once(block=True)

    def _drain_once(self, *, block: bool) -> None:
        try:
            first = self._q.get(timeout=0.2) if block else self._q.get_nowait()
        except queue.Empty:
            return
        batch = [first]
        while True:
            try:
                batch.append(self._q.get_nowait())
            except queue.Empty:
                break
        self._write(batch)

    def _write(self, batch: list[dict]) -> None:
        self._roll_day()
        if self._fh is None:
            self._fh = self._cur.open("a", encoding="utf-8")
        for rec in batch:
            line = json.dumps(rec, default=str) + "\n"
            nbytes = len(line.encode("utf-8"))
            self._fh.write(line)
            self._bytes_today += nbytes
            if self._active_run:
                self._run_bytes += nbytes
        self._fh.flush()
        if self._cur.exists() and self._cur.stat().st_size >= self._file_cap:
            self._rotate()
        self._evict()

    def _rotate(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        # Collision-proof name: the ms timestamp alone is NOT unique — two rotations in the
        # same millisecond produce the same name, which on Windows raises FileExistsError
        # (rename won't overwrite) and on POSIX SILENTLY overwrites the earlier rotated file
        # (data loss with no error). Append a monotonic counter until the name is free,
        # checking both the .jsonl and the deferred/compressed .jsonl.gz form.
        base = int(self._clock() * 1000)
        n = 0
        while ((self.dir / f"debug-{base}-{n}.jsonl").exists()
               or (self.dir / f"debug-{base}-{n}.jsonl.gz").exists()):
            n += 1
        rotated = self.dir / f"debug-{base}-{n}.jsonl"
        self._cur.rename(rotated)
        if self.cfg.compress_rotated:
            if self._active_run:
                self._pending_gz.append(rotated)   # defer: never gzip during a run (§3.3)
            else:
                self._gzip(rotated)

    def _compress_pending(self) -> None:
        for p in list(self._pending_gz):
            if p.exists():
                self._gzip(p)
            self._pending_gz.remove(p)

    @staticmethod
    def _gzip(path: Path) -> None:
        gz = path.with_name(path.name + ".gz")
        with path.open("rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        path.unlink()

    def _rolled(self) -> list[Path]:
        # Name is the tiebreak so same-ms rotations (equal mtime) sort deterministically
        # oldest→newest by their monotonic counter — eviction and read-back stay ordered.
        return sorted(self.dir.glob("debug-*.jsonl*"), key=lambda f: (f.stat().st_mtime, f.name))

    def _evict(self) -> None:
        files = self._rolled()
        total = sum(f.stat().st_size for f in files)
        if self._cur.exists():
            total += self._cur.stat().st_size
        i = 0
        while total > self._total_cap and i < len(files):   # size cap authoritative
            total -= files[i].stat().st_size
            files[i].unlink()
            i += 1
        if self.cfg.retention_days:                          # additional constraint
            cutoff = self._clock() - self.cfg.retention_days * 86400
            for f in self._rolled():
                if f.stat().st_mtime < cutoff:
                    f.unlink()

    # --- read-back (feeds GET /debug/rolling) ------------------------------

    @staticmethod
    def _run_id(rec: dict) -> str | None:
        def dig(v):
            if isinstance(v, dict):
                if v.get("run_id"):
                    return str(v["run_id"])
                for sub in v.values():
                    got = dig(sub)
                    if got:
                        return got
            return None
        return dig(rec.get("payload"))

    def read(self, *, since: float | None = None, until: float | None = None,
             run_id: str | None = None):
        """Yield record dicts from the on-disk sink (rotated oldest→newest, then the
        current file), server-side filtered by ts window + run_id."""
        files = self._rolled()
        if self._cur.exists():
            files.append(self._cur)
        for f in files:
            opener = gzip.open if f.name.endswith(".gz") else open
            try:
                with opener(f, "rt", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = rec.get("ts")
                        if since is not None and (ts is None or ts < since):
                            continue
                        if until is not None and (ts is None or ts > until):
                            continue
                        if run_id is not None and self._run_id(rec) != run_id:
                            continue
                        yield rec
            except OSError:
                continue

    # --- volume self-measurement (feeds /debug/health) ---------------------

    def metrics(self) -> dict:
        self._roll_day()
        avg = int(sum(self._run_samples) / len(self._run_samples)) if self._run_samples else 0
        proj_mb = round(self._bytes_today / _MB, 2)
        free = shutil.disk_usage(self.dir).free
        rate = self._bytes_today or 1
        days = int(self._total_cap / rate) if rate else None
        return {
            "rolling_dropped": self.dropped,
            "bytes_written_today": self._bytes_today,
            "bytes_per_run_avg": avg,
            "projected_mb_per_day": proj_mb,
            "disk_free_mb": round(free / _MB),
            "days_retained_at_current_rate": days,
        }

    # --- day roll ----------------------------------------------------------

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self._clock()))

    def _roll_day(self) -> None:
        d = self._today()
        if d != self._day:
            self._day = d
            self._bytes_today = 0

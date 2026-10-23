"""The Debug Tool's engine: live recorder + read-only log views + the operations MCP tools and the UI call.

It WRAPS `backend/debug_server` (Ingestor ring, RollingSink, SnapshotBuffer, LogDiscipline, capture, export) - nothing
there is re-implemented. Two modes, chosen at start:

  own     nothing else is recording: this engine runs the recorder and writes `<data>/recorder/` (rolling files + snapshots)
  attach  the app's own in-app Debug Server (`run.exe --debug-server`, :8001) is already recording: this engine keeps a
          MEMORY-ONLY ring (no rolling sink, no snapshots) and reads the in-app recorder's files read-only for history.
          There is never a second writer in `data/debug/`.

Passive operations (events, traces, follow, logs, instrument history, why) are read-only. Action operations (level change,
capture, export, file read, instrument probe, script) live here as plain methods but the MCP layer only calls them AFTER a
human approved that exact request (consent.ApprovalQueue); this class does not decide policy.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import json
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from debug_server.capture import CapturedRecord
from debug_server.config import DebugConfig
from debug_server.ingest import Ingestor
from debug_tool import compat, tails
from debug_tool.appinfo import AppInfo
from debug_tool.live import run_all_stations
from tmf_debug.api import select_run, why as api_why
from tmf_debug.instrument import instrument_digest

LEVELS = ("debug", "info", "warning", "error", "critical")
DEFAULT_PORT = 8010


def tcp_listening(host: str, port: int, timeout: float = 0.4) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


@dataclass
class EngineConfig:
    app: AppInfo
    data_dir: Path                          # the tool's OWN state: recorder (own mode), bundles, scripts, access log
    bind_host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    ring_capacity: int = 50_000
    force_mode: str | None = None           # "own" | "attach" | None = auto-detect
    in_app_probe: Callable[[int], bool] = lambda port: tcp_listening("127.0.0.1", port)   # noqa: E731
    tool_dir: Path | None = None            # where the tool lives: python-embed*.zip and wheelhouse/ are looked up here


def normalise(rec: CapturedRecord | dict) -> dict:
    """One record shape for everything Claude sees (MQTT events/diag/values, DB logs, launcher lines)."""
    d = rec.to_dict() if isinstance(rec, CapturedRecord) else dict(rec)
    if "source" in d and d.get("source") in ("error_log", "action_log", "launcher"):
        return d
    kind = d.get("kind") or "mqtt"
    payload = d.get("payload")
    ctx = payload.get("context") if isinstance(payload, dict) else None
    return {"source": "diag" if kind == "diag" else "mqtt", "ts": d.get("ts"), "level": d.get("level") or "info",
            "subsystem": d.get("subsystem"), "message": d.get("message") or d.get("type") or d.get("subtopic"),
            "topic": d.get("subtopic") or d.get("topic"), "type": d.get("type"), "trace": d.get("trace"),
            "station": d.get("station"), "seq": d.get("seq"),
            "context": ctx if ctx is not None else (payload if kind in ("event", "status") else None)}


def _trim(row: dict, limit: int = 600) -> dict:
    ctx = row.get("context")
    if ctx is not None and len(json.dumps(ctx, default=str)) > limit:
        row = {**row, "context": json.dumps(ctx, default=str)[:limit] + "...(trimmed)"}
    return row


def read_recorder_files(directory: Path | None, *, limit: int = 200_000) -> list[dict]:
    """Records from a recorder directory (rolling .jsonl + rotated .jsonl.gz), oldest first. READ-ONLY - never creates
    the directory, never takes a write handle (this is how attach mode reads the in-app recorder)."""
    if directory is None or not Path(directory).is_dir():
        return []
    out: list[dict] = []
    files = sorted((p for p in Path(directory).iterdir() if p.is_file() and (p.suffix == ".jsonl" or p.name.endswith(".jsonl.gz"))
                    and "snapshot" not in p.name.lower()), key=lambda p: p.stat().st_mtime)
    for f in files:
        try:
            fh = gzip.open(f, "rt", encoding="utf-8", errors="replace") if f.suffix == ".gz" else f.open("r", encoding="utf-8", errors="replace")
            with fh:
                for line in fh:
                    try:
                        v = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(v, dict):
                        out.append(v)
                        if len(out) >= limit:
                            return out
        except OSError:
            continue
    return out


class Engine:
    def __init__(self, cfg: EngineConfig, *, subscriber=run_all_stations, http_factory=None, clock=time.time) -> None:
        self.cfg = cfg
        self.app = cfg.app
        self.mode = "own"
        self._subscriber = subscriber
        self._http_factory = http_factory
        self._clock = clock
        self.ingestor: Ingestor | None = None
        self.rolling = None
        self.snapshot = None
        self._sub_task: asyncio.Task | None = None
        self.live_connected = False
        self.started_at: float | None = None
        self.level_reverts: dict[str, dict] = {}           # subsystem -> {task, previous, due}
        self.min_ttl_minutes = 1.0                          # a debug level never lingers: 1 min .. 240 min (tests shorten it)
        self.downloads: dict[str, Path] = {}               # id -> file created by an APPROVED export
        self.notes: list[str] = []
        from debug_tool.probe import InstrumentProbe
        from debug_tool.pyenv import PythonEnv
        from debug_tool.scripts import ScriptRunner
        self.pyenv = PythonEnv(cfg.tool_dir, cfg.data_dir / "python")
        self.scripts = ScriptRunner(cfg.data_dir / "scripts", self.pyenv.resolve, clock=clock)
        self.probe = InstrumentProbe(self)

    # ------------------------------------------------------------------ lifecycle

    def _decide_mode(self) -> str:
        if self.cfg.force_mode in ("own", "attach"):
            return self.cfg.force_mode
        port = self.app.in_app_recorder_port()
        return "attach" if self.cfg.in_app_probe(port) else "own"

    async def start(self) -> None:
        self.mode = self._decide_mode()
        dc = DebugConfig(station=self.app.stations()[0], ring_capacity=self.cfg.ring_capacity)
        self.ingestor = Ingestor(dc.station, capacity=dc.ring_capacity, orphan_timeout_s=dc.orphan_timeout_s)
        if self.mode == "own":
            from debug_server.logdiscipline import LogDiscipline, load_variable_meta
            from debug_server.rollingsink import RollingSink
            from debug_server.snapshot import SnapshotBuffer
            rec_dir = self.cfg.data_dir / "recorder"
            dc.rolling.dir = str(rec_dir)
            self.rolling = RollingSink(dc.rolling, rec_dir, queue_size=dc.limits.queue_size)
            self.snapshot = SnapshotBuffer(dc.snapshot, rec_dir)
            self.ingestor.rolling, self.ingestor.snapshot = self.rolling, self.snapshot
            self.ingestor.discipline = LogDiscipline(dc.analog, dc.digital, dc.limits,
                                                     load_variable_meta(self.app.app_config), self.rolling.enqueue)
            self.rolling.start()
        else:
            self.notes.append(f"attach mode: the in-app recorder is on :{self.app.in_app_recorder_port()} - this tool keeps a "
                              "memory-only ring and reads its files read-only (one writer in data/debug/)")
        host, port = self.app.broker()
        self._sub_task = asyncio.create_task(self._subscriber(self.ingestor, host, port, on_state=self._on_live_state))
        self.started_at = self._clock()

    def _on_live_state(self, connected: bool) -> None:
        self.live_connected = connected

    async def stop(self) -> None:
        for r in list(self.level_reverts.values()):
            t = r.get("task")
            if t:
                t.cancel()
        if self._sub_task:
            self._sub_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._sub_task
        if self.snapshot is not None:
            with contextlib.suppress(Exception):
                self.snapshot.flush_due()
        if self.rolling is not None:
            with contextlib.suppress(Exception):
                self.rolling.stop()

    # ------------------------------------------------------------------ passive reads

    def _history_dir(self) -> Path | None:
        return (self.cfg.data_dir / "recorder") if self.mode == "own" else self.app.debug_dir

    def health(self) -> dict:
        ing = self.ingestor
        h = ing.health() if ing else {}
        return {"tool": "tmf-debug-tool", "mode": self.mode, "uptime_s": int(self._clock() - self.started_at) if self.started_at else 0,
                "app": self.app.as_dict(), "recorder": h, "live": {"mqtt": "connected" if self.live_connected else "disconnected",
                "broker": "%s:%s" % self.app.broker(), "stations": self.app.stations(),
                "db": "available" if self.app.db_path and self.app.db_path.is_file() else "missing",
                "launcher_log": "available" if self.app.launcher_log and self.app.launcher_log.is_file() else "missing"},
                "level_reverts_pending": {k: {"previous": v["previous"], "due_in_s": max(0, int(v["due"] - self._clock()))}
                                          for k, v in self.level_reverts.items()},
                "compat": compat.check(self.app.framework_version), "notes": self.notes}

    def run_active(self) -> bool:
        """A test run is in progress (from run-started/finished events seen since the tool started)."""
        return bool(self.ingestor and self.ingestor._active)

    def events(self, *, since=None, level=None, subsystem=None, topic=None, trace=None, kind=None, text=None, limit=500) -> list[dict]:
        return [r.to_dict() for r in self.ingestor.ring.query(since=since, level=level, subsystem=subsystem, topic=topic,
                                                              trace=trace, kind=kind, text=text, limit=limit)]

    def traces(self) -> list[dict]:
        return self.ingestor.traces()

    def trace(self, trace: str) -> list[dict]:
        return self.ingestor.trace(trace)

    def requests(self, status=None) -> list[dict]:
        return self.ingestor.requests(status)

    def liveness(self) -> list[dict]:
        return self.ingestor.liveness_grid()

    def violations(self) -> list[dict]:
        return self.ingestor.violations()

    def snapshots(self) -> list[dict]:
        if self.snapshot is not None:
            return self.snapshot.list()
        d = self.app.debug_dir
        if d is None or not d.is_dir():
            return []
        return [{"id": p.stem, "bytes": p.stat().st_size, "ts": p.stat().st_mtime, "source": "in-app recorder (read-only)"}
                for p in sorted(d.glob("snapshot*.jsonl"))]

    def snapshot_text(self, sid: str) -> str | None:
        if self.snapshot is not None:
            return self.snapshot.read(sid)
        d = self.app.debug_dir
        p = (d / f"{sid}.jsonl") if d else None
        return p.read_text(encoding="utf-8", errors="replace") if p and p.is_file() and p.resolve().parent == d.resolve() else None

    def records_for_analysis(self) -> list[dict]:
        ring = [r.to_dict() for r in self.ingestor.ring.all()]
        if ring and any(r.get("type") == "run-started" for r in ring):
            return ring
        hist = read_recorder_files(self._history_dir())
        return (hist + ring) if hist else ring

    def why(self, run: str | None = None, *, out_dir: Path | None = None) -> dict | None:
        recs = self.records_for_analysis()
        out = api_why(recs, out_dir=out_dir or (self.cfg.data_dir / "analysis"), prefix="bench", run=run, last=run is None)
        return out

    def instruments(self, instance_id: str | None = None) -> dict:
        recs = [r for r in self.records_for_analysis() if r.get("subsystem") == "instrument"]
        d = instrument_digest(recs, instance_id=instance_id)
        d["live_mqtt"] = "connected" if self.live_connected else "disconnected"
        return d

    def logs(self, source: str, *, since: float | None = None, tail: int = 100, level: str | None = None) -> dict:
        if source in ("diag", "mqtt"):
            rows = [normalise(r) for r in self.ingestor.ring.query(level=level, kind="diag" if source == "diag" else None, limit=tail)]
            return {"rows": [_trim(r) for r in rows if since is None or (r.get("ts") or 0) > since]}
        out = tails.read_log(source, db=self.app.db_path, launcher=self.app.launcher_log, since_ts=since, tail=tail, level=level)
        out["rows"] = [_trim(r) for r in out["rows"]]
        return out

    async def follow(self, *, seconds: float = 20.0, sources=("mqtt", "logs"), subsystem: str | None = None,
                     level: str | None = None, topic: str | None = None, text: str | None = None, max_events: int = 200) -> dict:
        """Collect what the RUNNING app emits for a bounded window: MQTT events/diag/values from the live ring queue plus new
        error_log / action_log rows and launcher lines. Bounded by seconds AND events; reports what was dropped."""
        seconds = max(0.5, min(float(seconds), 120.0))
        want_mqtt = "mqtt" in sources or "both" in sources
        want_logs = "logs" in sources or "both" in sources
        q = self.ingestor.subscribe() if want_mqtt else None
        t_db = tails.DbTail(self.app.db_path, "error_log", start_ts=self._clock()) if want_logs else None
        t_act = tails.DbTail(self.app.db_path, "action_log", start_ts=self._clock()) if want_logs else None
        t_file = tails.FileTail(self.app.launcher_log) if want_logs else None
        events: list[dict] = []
        counts: dict[str, int] = {}
        truncated = False
        end = self._clock() + seconds
        lv = LEVELS.index(level) if level in LEVELS else None
        try:
            while self._clock() < end and not truncated:
                if q is not None:
                    try:
                        rec = await asyncio.wait_for(q.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        rec = None
                    while rec is not None:
                        row = normalise(rec)
                        ok = (not subsystem or row.get("subsystem") == subsystem) and (not topic or (row.get("topic") or "").startswith(topic))
                        ok = ok and (lv is None or (row.get("level") in LEVELS and LEVELS.index(row["level"]) >= lv))
                        ok = ok and (not text or text.lower() in json.dumps(row, default=str).lower())
                        if ok:
                            events.append(_trim(row))
                            counts[row["source"]] = counts.get(row["source"], 0) + 1
                            if len(events) >= max_events:
                                truncated = True
                                break
                        try:
                            rec = q.get_nowait()
                        except asyncio.QueueEmpty:
                            rec = None
                else:
                    await asyncio.sleep(0.25)
                if want_logs:
                    for t in (t_db, t_act, t_file):
                        for row in t.poll(level):
                            if (not subsystem or row.get("subsystem") == subsystem) and (not text or text.lower() in json.dumps(row, default=str).lower()):
                                events.append(_trim(row))
                                counts[row["source"]] = counts.get(row["source"], 0) + 1
                                if len(events) >= max_events:
                                    truncated = True
                                    break
        finally:
            if q is not None:
                self.ingestor.unsubscribe(q)
        events.sort(key=lambda r: r.get("ts") or 0)
        return {"window_s": seconds, "events": events, "counts": counts, "truncated": truncated,
                "live": {"mqtt": "connected" if self.live_connected else "disconnected"},
                "note": ("stopped at max_events - narrow the filters or raise max_events" if truncated else
                         "mqtt is disconnected: only logs were available" if want_mqtt and not self.live_connected else "")}

    # ------------------------------------------------------------------ core relay (level control; the core's own gate applies)

    def _client(self):
        import httpx
        return self._http_factory() if self._http_factory else httpx.AsyncClient(timeout=6.0)

    async def _core(self, method: str, path: str, token: str | None, body: dict | None = None) -> dict:
        if not token:
            raise PermissionError("this needs a core login token with SYSTEM.SETTINGS - set it on the MCP connection "
                                  "(header X-Core-Token); the debug token is deliberately not accepted by the core")
        async with self._client() as c:
            r = await c.request(method, self.app.core_url().rstrip("/") + path, headers={"Authorization": f"Bearer {token}"}, json=body)
        if r.status_code >= 400:
            detail = ""
            with contextlib.suppress(Exception):
                detail = r.json().get("detail", "")
            raise RuntimeError(f"core answered {r.status_code} for {path}: {detail or r.text[:160]}")
        return r.json()

    async def level_get(self, token: str | None) -> dict:
        return await self._core("GET", "/diag/level", token)

    async def level_set(self, subsystem: str, level: str, ttl_minutes: float, token: str | None) -> dict:
        if level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}")
        ttl = max(self.min_ttl_minutes, min(float(ttl_minutes), 240.0))
        cur = await self.level_get(token)
        previous = (cur.get("overrides") or {}).get(subsystem) or cur.get("default") or "warning"
        res = await self._core("PUT", "/diag/level", token, {"subsystem": subsystem, "level": level})
        old = self.level_reverts.pop(subsystem, None)
        if old and old.get("task"):
            old["task"].cancel()
            previous = old["previous"]                       # keep the ORIGINAL level across repeated changes
        due = self._clock() + ttl * 60.0
        self.level_reverts[subsystem] = {"previous": previous, "due": due,
                                         "task": asyncio.create_task(self._revert_level(subsystem, previous, ttl * 60.0, token))}
        return {"applied": res.get("applied"), "will_revert_to": previous, "revert_in_minutes": ttl}

    async def _revert_level(self, subsystem: str, previous: str, delay_s: float, token: str | None) -> None:
        try:
            await asyncio.sleep(delay_s)
            await self._core("PUT", "/diag/level", token, {"subsystem": subsystem, "level": previous})
            self.level_reverts.pop(subsystem, None)
            self.notes.append(f"level of '{subsystem}' reverted to {previous}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:                              # noqa: BLE001 - say loudly that the revert did NOT happen
            self.notes.append(f"LEVEL REVERT FAILED for '{subsystem}' (should be {previous}): {exc} - set it back by hand")
            self.level_reverts[subsystem] = {**self.level_reverts.get(subsystem, {}), "previous": previous, "due": self._clock(), "task": None}

    # ------------------------------------------------------------------ capture + export

    def capture_start(self, name: str) -> dict:
        return {"capture_id": self.ingestor.capture_start(name), "name": name}

    def capture_stop(self, cid: str) -> dict:
        return {"capture_id": cid, "records": self.ingestor.capture_stop(cid)}

    def capture_export(self, cid: str) -> str | None:
        return self.ingestor.export_jsonl(cid)

    async def export_bundle(self, *, rows: int = 5000, integrity: bool = True, out_dir: Path | None = None,
                            register: bool = True) -> dict:
        """Build the offline diagnostics bundle (the same zip as `run.exe --debug-export`) into the tool's own folder (or
        `out_dir`) and, for a remote request, register it for download. Runs in a thread: it shells out to PowerShell/netstat
        and hashes the install."""
        from debug_server.export import export_bundle as _export
        out_dir = Path(out_dir) if out_dir else self.cfg.data_dir / "bundles"
        name = f"tmf-debug-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        out = out_dir / name
        if not self.app.found:
            raise RuntimeError("no app install found - nothing to export (pass --state-dir)")
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = await asyncio.to_thread(_export, out, state_root=self.app.state_root, rows=rows,
                                           bundle_root_override=self.app.bundle_root, integrity=integrity)
        res = {"file": name, "bytes": out.stat().st_size, "path": str(out), "files": len(manifest["files"]),
               "missing": manifest["missing"]}
        if register:
            import secrets
            did = secrets.token_hex(8)
            self.downloads[did] = out
            res.update(download_id=did, download_url=f"/files/{did}")
        return res

    def analyze_bundle(self, zip_path: Path | str, *, name: str | None = None) -> dict:
        """Read a bundle zip back (the same analyser `tmf-debug-tool analyze` uses) into the tool's own `analyses/` folder."""
        from tmf_debug.bundle import analyze
        a = analyze(Path(zip_path), self.cfg.data_dir / "analyses", name=name)
        a["markdown"] = Path(a["paths"]["analysis_md"]).read_text(encoding="utf-8", errors="replace")
        return a

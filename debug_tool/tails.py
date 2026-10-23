"""Read-only views of the app's own logs, normalised to one record shape.

Sources (what the app actually writes - there are no other plain-text app logs):
  error_log / action_log   the station DB `records` table, opened `mode=ro` (never takes a write lock, never creates it)
  launcher                 `<state>/data/launcher.log` (relaunches, update swaps)

Every row is `{source, ts, level, subsystem, message, context, id}` so Claude can correlate "step failed (MQTT event)"
with "error_log row" with "launcher relaunched". Nothing here ever raises: a missing/locked/odd file yields no rows and a
`note`, because a diagnostics tool that dies on the broken thing it was asked to diagnose is useless.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import deque
from pathlib import Path

LEVELS = ("debug", "info", "warning", "error", "critical")
_LAUNCHER_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(?:launcher:\s*)?(.*)$")


def _lvl_ok(level: str | None, minimum: str | None) -> bool:
    if not minimum or minimum not in LEVELS:
        return True
    return level in LEVELS and LEVELS.index(level) >= LEVELS.index(minimum)


def _row(source: str, rid, ts, data: dict, summary: str | None) -> dict:
    d = data if isinstance(data, dict) else {"message": str(data)}
    level = d.get("level")
    if source == "action_log":
        level = level or ("warning" if str(d.get("result", "")).lower() == "failure" else "info")
    return {"source": source, "id": rid, "ts": ts, "level": level or "info",
            "subsystem": d.get("subsystem") or d.get("source") or d.get("principal") or d.get("user"),
            "message": d.get("message") or d.get("action") or summary,
            "context": d.get("context") if "context" in d else {k: v for k, v in d.items()
                                                                if k not in ("level", "subsystem", "message", "source", "ts")}}


def _connect_ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=3)


def read_db_log(db: Path | None, record_type: str, *, since_ts: float | None = None, tail: int = 100,
                level: str | None = None) -> dict:
    """`{rows: [...], note?}` newest `tail` rows of an error_log/action_log, oldest first."""
    if db is None or not Path(db).is_file():
        return {"rows": [], "note": f"station DB not found ({db}) - the app has never run here, or the state dir is wrong"}
    try:
        con = _connect_ro(db)
    except sqlite3.Error as exc:
        return {"rows": [], "note": f"station DB could not be opened read-only: {exc}"}
    try:
        sql = "SELECT id, ts, summary, data FROM records WHERE type=?" + (" AND ts>?" if since_ts is not None else "")
        args: list = [record_type] + ([since_ts] if since_ts is not None else [])
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, int(tail)) * (4 if level else 1))
        rows = []
        for rid, ts, summary, data in con.execute(sql, args):
            try:
                payload = json.loads(data)
            except ValueError:
                payload = {"message": str(data)[:300]}
            r = _row(record_type, rid, ts, payload, summary)
            if _lvl_ok(r["level"], level):
                rows.append(r)
        rows.reverse()
        return {"rows": rows[-tail:]}
    except sqlite3.Error as exc:
        return {"rows": [], "note": f"could not read {record_type}: {exc}"}
    finally:
        con.close()


def _launcher_level(line: str) -> str:
    low = line.lower()
    if any(w in low for w in ("failed", "error", "traceback", "exception")):
        return "error"
    if any(w in low for w in ("blocked", "retry", "rollback", "relaunch", "warn")):
        return "warning"
    return "info"


def read_launcher(path: Path | None, *, tail: int = 100, since_ts: float | None = None, level: str | None = None) -> dict:
    if path is None or not Path(path).is_file():
        return {"rows": [], "note": f"launcher.log not found ({path}) - the app was started without the launcher, or never relaunched"}
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
            lines = deque((ln.rstrip("\n") for ln in fh), maxlen=max(tail * 4, 400))
    except OSError as exc:
        return {"rows": [], "note": f"launcher.log unreadable: {exc}"}
    rows: list[dict] = []
    last_ts: float | None = None
    for ln in lines:
        if not ln.strip():
            continue
        m = _LAUNCHER_TS.match(ln)
        ts = None
        msg = ln
        if m:
            try:
                ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                msg = m.group(2)
            except ValueError:
                pass
        ts = ts if ts is not None else last_ts
        last_ts = ts
        lv = _launcher_level(msg)
        if since_ts is not None and (ts is None or ts <= since_ts):
            continue
        if _lvl_ok(lv, level):
            rows.append({"source": "launcher", "id": None, "ts": ts, "level": lv, "subsystem": "launcher",
                         "message": msg, "context": {}})
    return {"rows": rows[-tail:]}


def read_log(source: str, *, db: Path | None, launcher: Path | None, since_ts: float | None = None, tail: int = 100,
             level: str | None = None) -> dict:
    if source in ("error_log", "action_log"):
        return read_db_log(db, source, since_ts=since_ts, tail=tail, level=level)
    if source == "launcher":
        return read_launcher(launcher, tail=tail, since_ts=since_ts, level=level)
    return {"rows": [], "note": f"unknown log source {source!r} (error_log | action_log | launcher; diag/mqtt come from the live recorder)"}


class DbTail:
    """Polls a DB log for rows newer than what it has already returned (used by `follow`)."""

    def __init__(self, db: Path | None, record_type: str, *, start_ts: float | None = None) -> None:
        self.db, self.type = db, record_type
        self.last = time.time() if start_ts is None else start_ts

    def poll(self, level: str | None = None) -> list[dict]:
        got = read_db_log(self.db, self.type, since_ts=self.last, tail=500, level=level)["rows"]
        if got:
            self.last = max(r["ts"] for r in got if isinstance(r.get("ts"), (int, float))) if any(
                isinstance(r.get("ts"), (int, float)) for r in got) else self.last
        return got


class FileTail:
    """Reads only what a text file has gained since the last poll (launcher.log)."""

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self.pos = self.path.stat().st_size if self.path and self.path.is_file() else 0

    def poll(self, level: str | None = None) -> list[dict]:
        if not self.path or not self.path.is_file():
            return []
        try:
            size = self.path.stat().st_size
            if size < self.pos:                       # rotated / truncated
                self.pos = 0
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self.pos)
                chunk = fh.read()
                self.pos = fh.tell()
        except OSError:
            return []
        rows = []
        now = time.time()
        for ln in chunk.splitlines():
            if not ln.strip():
                continue
            m = _LAUNCHER_TS.match(ln)
            msg = m.group(2) if m else ln
            lv = _launcher_level(msg)
            if _lvl_ok(lv, level):
                rows.append({"source": "launcher", "id": None, "ts": now, "level": lv, "subsystem": "launcher",
                             "message": msg, "context": {}})
        return rows

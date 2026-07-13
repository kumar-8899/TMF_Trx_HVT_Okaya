"""Local durable outbox for reports (write-ahead spool).

Run-finish writes the assembled report here FIRST (a tiny local SQLite file, separate
from the station records DB), so testing never blocks on and never loses a report if the
professional DB is unreachable. A forwarder drains it to the ReportStore and retries.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import aiosqlite

_DDL = """
CREATE TABLE IF NOT EXISTS report_outbox (
    run_id     TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_ts REAL NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
"""


class Outbox:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_DDL)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def enqueue(self, report: dict) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO report_outbox (run_id, payload, created_ts, attempts, last_error) "
            "VALUES (?, ?, ?, 0, NULL)",
            (report["run_id"], json.dumps(report), time.time()))
        await self._conn.commit()

    async def pending(self, limit: int = 100) -> list[dict]:
        async with self._conn.execute(
            "SELECT run_id, payload, attempts FROM report_outbox ORDER BY created_ts LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [{"run_id": r["run_id"], "report": json.loads(r["payload"]), "attempts": r["attempts"]} for r in rows]

    async def count(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM report_outbox") as cur:
            return (await cur.fetchone())[0]

    async def mark_done(self, run_id: str) -> None:
        await self._conn.execute("DELETE FROM report_outbox WHERE run_id=?", (run_id,))
        await self._conn.commit()

    async def mark_failed(self, run_id: str, error: str) -> None:
        await self._conn.execute(
            "UPDATE report_outbox SET attempts=attempts+1, last_error=? WHERE run_id=?", (error[:500], run_id))
        await self._conn.commit()

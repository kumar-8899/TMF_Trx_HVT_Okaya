"""Database service (CORE.md §1, §7).

Per-station embedded SQLite (decision in PRINCIPLES locked-decisions follow-up:
SQLite fits the station deployment unit + singleton). The base Repository stamps
every record with the RAG metadata envelope (PRINCIPLES §5), so a module cannot
persist a record without it. Records are append-only where the domain allows.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS records (
    id             TEXT NOT NULL,
    type           TEXT NOT NULL,
    ts             REAL NOT NULL,
    station        TEXT NOT NULL,
    source_version TEXT NOT NULL,
    summary        TEXT,
    data           TEXT NOT NULL,
    PRIMARY KEY (type, id)
);
CREATE INDEX IF NOT EXISTS idx_records_type_ts ON records(type, ts);

CREATE TABLE IF NOT EXISTS schema_migrations (
    name       TEXT PRIMARY KEY,
    applied_at REAL NOT NULL
);
"""


def _row_to_record(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "ts": row["ts"],
        "station": row["station"],
        "source_version": row["source_version"],
        "summary": row["summary"],
        "data": json.loads(row["data"]),
    }


class Repository:
    """Stamps the RAG envelope on every write (CORE.md §7)."""

    def __init__(self, conn: aiosqlite.Connection, station: str, source_version: str) -> None:
        self._conn = conn
        self._station = station
        self._source_version = source_version

    async def put(
        self,
        record_type: str,
        payload: dict,
        *,
        id: str | None = None,
        summary: str | None = None,
    ) -> str:
        rec_id = id or str(uuid.uuid4())
        await self._conn.execute(
            "INSERT OR REPLACE INTO records "
            "(id, type, ts, station, source_version, summary, data) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                rec_id,
                record_type,
                time.time(),
                self._station,
                self._source_version,
                summary,
                json.dumps(payload),
            ),
        )
        await self._conn.commit()
        return rec_id

    async def get(self, record_type: str, id: str) -> dict | None:
        async with self._conn.execute(
            "SELECT * FROM records WHERE type=? AND id=?", (record_type, id)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_record(row) if row else None

    async def query(
        self,
        record_type: str,
        filter: dict | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM records WHERE type=?"
        args: list[Any] = [record_type]
        for key, value in (filter or {}).items():
            sql += " AND json_extract(data, ?) = ?"
            args.extend([f"$.{key}", value])
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since)
        if until is not None:
            sql += " AND ts <= ?"
            args.append(until)
        sql += " ORDER BY ts ASC, rowid ASC"  # insertion-stable at equal ts
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        async with self._conn.execute(sql, args) as cur:
            rows = await cur.fetchall()
        return [_row_to_record(r) for r in rows]

    async def delete(self, record_type: str, before_ts: float) -> int:
        """Delete records older than before_ts. The sanctioned non-append op,
        for log pruning + admin purge only (CORE.md §7 'where the domain allows')."""
        cur = await self._conn.execute(
            "DELETE FROM records WHERE type=? AND ts < ?", (record_type, before_ts)
        )
        await self._conn.commit()
        return cur.rowcount


class Database:
    def __init__(self, path: Path | str, station: str = "st1", source_version: str = "0.0.0") -> None:
        self.path = str(path)
        self.station = station
        self.source_version = source_version
        self._conn: aiosqlite.Connection | None = None

    @property
    def connected(self) -> bool:
        return self._conn is not None

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_BOOTSTRAP)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def repo(self) -> Repository:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return Repository(self._conn, self.station, self.source_version)

    async def run_migrations(self, directory: Path | str | None) -> list[str]:
        """Apply unseen `*.sql` files from a module's migrations dir, in name order."""
        if self._conn is None:
            raise RuntimeError("Database not connected")
        if directory is None:
            return []
        directory = Path(directory)
        if not directory.exists():
            return []
        applied: list[str] = []
        for sql_file in sorted(directory.glob("*.sql")):
            key = f"{directory.name}/{sql_file.name}"
            async with self._conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name=?", (key,)
            ) as cur:
                if await cur.fetchone():
                    continue
            await self._conn.executescript(sql_file.read_text(encoding="utf-8"))
            await self._conn.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                (key, time.time()),
            )
            await self._conn.commit()
            applied.append(key)
        return applied

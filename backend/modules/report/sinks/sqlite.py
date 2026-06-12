"""SQLite report sink — the always-on queryable system-of-record (RAG envelope)."""

from __future__ import annotations


class SqliteSink:
    method_id = "sqlite"

    def __init__(self, db, when: str = "all") -> None:
        self._db = db
        self.when = when

    async def write(self, report: dict) -> None:
        await self._db.repo.put("report", report, id=report["run_id"], summary=report["summary"])

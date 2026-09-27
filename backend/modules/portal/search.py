"""In-memory full-text search over the portal's corpus (library PDF text + titles + tags).

SQLite FTS5 in a private `:memory:` connection — no schema in the station database (the shared
`records` table stays the only persisted structure; core-services.md: "don't invent ad-hoc tables"),
rebuilt from the durable records + text files at start-up and after every library change. A station has
tens of documents, so a rebuild is milliseconds. Falls back to a plain substring scan if this Python's
SQLite lacks FTS5, so search never disappears."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Doc:
    id: str
    title: str
    tags: str
    text: str


_WORD = re.compile(r"[\w][\w.\-]*", re.UNICODE)


def _fts_query(q: str) -> str | None:
    """User text -> a safe FTS5 query: every word must match (prefix on the last one)."""
    words = _WORD.findall(q)
    if not words:
        return None
    parts = ['"%s"' % w.replace('"', "") for w in words]
    parts[-1] += "*"
    return " ".join(parts)


class SearchIndex:
    def __init__(self) -> None:
        self._docs: dict[str, Doc] = {}
        self._db: sqlite3.Connection | None = None
        self.fts = True
        self.rebuild([])

    def rebuild(self, docs: list[Doc]) -> None:
        self._docs = {d.id: d for d in docs}
        try:
            db = sqlite3.connect(":memory:", check_same_thread=False)
            db.execute("CREATE VIRTUAL TABLE t USING fts5(id UNINDEXED, title, tags, body, tokenize='unicode61')")
            db.executemany("INSERT INTO t(id, title, tags, body) VALUES (?,?,?,?)",
                           [(d.id, d.title, d.tags, d.text) for d in docs])
            self._db, self.fts = db, True
        except sqlite3.OperationalError:            # no FTS5 in this SQLite build
            self._db, self.fts = None, False

    def query(self, q: str, limit: int = 20) -> list[dict]:
        q = q.strip()
        if not q:
            return []
        if self.fts and self._db is not None:
            match = _fts_query(q)
            if match is None:
                return []
            try:
                rows = self._db.execute(
                    "SELECT id, title, snippet(t, 3, '[', ']', '…', 14), bm25(t, 0.0, 8.0, 4.0, 1.0) "
                    "FROM t WHERE t MATCH ? ORDER BY bm25(t, 0.0, 8.0, 4.0, 1.0) LIMIT ?", (match, limit)).fetchall()
            except sqlite3.OperationalError:
                return []
            return [{"id": r[0], "title": r[1], "snippet": r[2] or "", "score": -r[3]} for r in rows]
        needle = q.lower()
        hits = []
        for d in self._docs.values():
            hay = f"{d.title}\n{d.tags}\n{d.text}".lower()
            i = hay.find(needle)
            if i >= 0:
                body = d.text
                j = body.lower().find(needle)
                snip = body[max(0, j - 50): j + 90].replace("\n", " ") if j >= 0 else ""
                hits.append({"id": d.id, "title": d.title, "snippet": snip, "score": 1.0})
        return hits[:limit]

"""DB service + RAG envelope (CORE.md §7)."""

import pytest

from core.services.db import Database


@pytest.fixture
async def db():
    d = Database(":memory:", station="st1", source_version="0.0.0")
    await d.connect()
    yield d
    await d.close()


async def test_put_stamps_rag_envelope(db):
    rec_id = await db.repo.put("run", {"result": "PASS"}, summary="run ok")
    rec = await db.repo.get("run", rec_id)
    assert rec["id"] == rec_id
    assert rec["type"] == "run"
    assert rec["station"] == "st1"
    assert rec["source_version"] == "0.0.0"
    assert rec["summary"] == "run ok"
    assert rec["data"] == {"result": "PASS"}
    assert isinstance(rec["ts"], float)


async def test_get_unknown_returns_none(db):
    assert await db.repo.get("run", "missing") is None


async def test_query_by_type_filter_since_limit(db):
    await db.repo.put("run", {"line": "A"}, id="r1")
    await db.repo.put("run", {"line": "B"}, id="r2")
    await db.repo.put("step", {"line": "A"}, id="s1")

    runs = await db.repo.query("run")
    assert {r["id"] for r in runs} == {"r1", "r2"}

    a_only = await db.repo.query("run", filter={"line": "A"})
    assert [r["id"] for r in a_only] == ["r1"]

    limited = await db.repo.query("run", limit=1)
    assert len(limited) == 1

    future = await db.repo.query("run", since=2_000_000_000.0)
    assert future == []


async def test_run_migrations_applies_once(db, tmp_path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_init.sql").write_text("CREATE TABLE widgets (id TEXT);")
    assert await db.run_migrations(mig) == ["migrations/001_init.sql"]
    # idempotent: already applied -> nothing
    assert await db.run_migrations(mig) == []


async def test_run_migrations_none_is_noop(db):
    assert await db.run_migrations(None) == []

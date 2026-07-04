"""Outbox tester — the durable local spool (enqueue → forward → delete; retry)."""

import pytest

from modules.report.outbox import Outbox


@pytest.fixture
async def box(tmp_path):
    b = Outbox(str(tmp_path / "outbox.sqlite"))
    await b.connect()
    yield b
    await b.close()


async def test_enqueue_pending_done(box):
    await box.enqueue({"run_id": "R1", "result": "PASS"})
    await box.enqueue({"run_id": "R2", "result": "FAIL"})
    assert await box.count() == 2
    pend = await box.pending()
    assert {p["run_id"] for p in pend} == {"R1", "R2"} and pend[0]["report"]["result"] == "PASS"
    await box.mark_done("R1")
    assert await box.count() == 1


async def test_enqueue_is_idempotent(box):
    await box.enqueue({"run_id": "R1", "result": "FAIL"})
    await box.enqueue({"run_id": "R1", "result": "PASS"})     # re-spool same run_id
    assert await box.count() == 1
    assert (await box.pending())[0]["report"]["result"] == "PASS"


async def test_mark_failed_tracks_attempts(box):
    await box.enqueue({"run_id": "R1"})
    await box.mark_failed("R1", "db down")
    await box.mark_failed("R1", "still down")
    assert (await box.pending())[0]["attempts"] == 2          # retained for retry

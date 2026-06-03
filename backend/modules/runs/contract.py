"""Runs contract (CORE.md §2, §7).

Run control is a thin proxy to the LabVIEW controller (run.start / run.abort).
Run records are persisted from event/run-* the controller emits.
"""

from __future__ import annotations

from typing import Protocol


class RunsContract(Protocol):
    async def run_start(self, params: dict | None = None) -> dict: ...
    async def run_abort(self) -> dict: ...
    async def list_runs(self, since: float | None = None, limit: int | None = None) -> list[dict]: ...
    async def get_run(self, run_id: str) -> dict | None: ...

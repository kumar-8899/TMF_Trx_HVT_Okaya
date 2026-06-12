"""Report contract (CORE.md §2). Siblings resolve via core.get_contract("report")."""

from __future__ import annotations

from typing import Protocol


class ReportContract(Protocol):
    async def get_report(self, run_id: str) -> dict | None: ...
    async def list_reports(
        self, since: float | None = None, until: float | None = None,
        recipe_id: str | None = None, result: str | None = None,
        limit: int = 200, cursor: str | None = None,
    ) -> dict: ...
    async def analytics(self, since: float | None = None, until: float | None = None,
                        recipe_id: str | None = None) -> dict: ...
    async def export(self, run_id: str, fmt: str = "json") -> bytes: ...

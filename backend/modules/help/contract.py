"""Help module contract (CORE.md §2). Read-only doc surface."""

from __future__ import annotations

from typing import Protocol


class HelpContract(Protocol):
    def index(self, *, include_dev: bool) -> list[dict]: ...
    def page(self, page_id: str) -> dict | None: ...
    def search(self, query: str, *, include_dev: bool) -> list[dict]: ...

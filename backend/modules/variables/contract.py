"""variables module contract (CORE.md §2). The scalar-signal surface."""

from __future__ import annotations

from typing import Protocol


class VariablesContract(Protocol):
    async def read(self, name: str) -> dict: ...
    async def write(self, name: str, value: float) -> dict: ...

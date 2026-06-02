"""The hello contract (CORE.md §2). Tiny — it exists to prove the seam."""

from __future__ import annotations

from typing import Protocol


class HelloContract(Protocol):
    async def ping(self) -> dict:
        """Round-trip to the LabVIEW stub and report liveness."""
        ...

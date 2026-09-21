"""Portal module contract (CORE.md §2). See docs/contracts/PORTAL.md."""

from __future__ import annotations

from typing import Protocol


class PortalContract(Protocol):
    async def init(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

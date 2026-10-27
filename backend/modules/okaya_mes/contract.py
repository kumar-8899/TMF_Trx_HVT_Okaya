"""okaya_mes contract: writes Okaya's legacy wide-row MES table. App-owned (this fork), nothing consumes it yet."""

from __future__ import annotations

from typing import Protocol


class OkayaMesContract(Protocol):
    async def status(self) -> dict: ...

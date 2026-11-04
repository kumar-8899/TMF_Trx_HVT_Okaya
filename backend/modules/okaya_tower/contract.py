"""okaya_tower contract: drives the relay2 tower stack from run state. App-owned (this fork)."""

from __future__ import annotations

from typing import Protocol


class OkayaTowerContract(Protocol):
    async def status(self) -> dict: ...

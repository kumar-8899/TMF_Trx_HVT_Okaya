"""MES interlock contract (CORE.md §2).

Cross-station interlock: gate a run on the previous stage's result, and publish
this stage's result for the next stage. Transport (folder/db/xml) is pluggable.
"""

from __future__ import annotations

from typing import Protocol

from core.services.interlock import InterlockResult


class MesContract(Protocol):
    async def check(self, serial: str, ctx: dict) -> InterlockResult: ...
    async def publish(self, serial: str, result: str, payload: dict) -> None: ...
    def status(self) -> dict: ...

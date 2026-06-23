"""Configuration contract (CORE.md §2).

A thin read surface other modules can lean on — notably the health module, which
will template its hardware checks against the configured instruments (the
instrument record carries `id`/`family`/`capabilities`, the shape health expects).
"""

from __future__ import annotations

from typing import Protocol


class ConfigContract(Protocol):
    async def list_instruments(self) -> list[dict]: ...
    def transports(self) -> list[dict]: ...

"""MES transport seam — the one interface every interlock backend implements.

Add a new MES type (folder / database / xml / …) by subclassing this and
registering it in the factory. The runs gate and the downstream publish never
know which transport is behind it.
"""

from __future__ import annotations

from core.services.interlock import InterlockResult


class MesProvider:
    """Abstract MES transport. Subclasses override check_upstream + publish_result."""

    async def check_upstream(self, serial: str) -> InterlockResult:
        """Has `serial` passed the previous stage?"""
        raise NotImplementedError

    async def publish_result(self, serial: str, result: str, payload: dict) -> None:
        """Record this stage's outcome for the next stage to gate on."""
        raise NotImplementedError

    def describe(self) -> dict:
        """UI-facing summary of where this provider reads/writes."""
        return {}

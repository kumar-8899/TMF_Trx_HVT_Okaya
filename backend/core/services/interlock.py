"""MES interlock port — the optional cross-station gate (CORE.md ports pattern).

The active MES module registers its upstream check here at init. Consumers (the
runs module) call `core.interlock.check(serial, ctx)` before starting a run and
never touch the MES package. If no MES module is loaded the port is **fail-open**
(always allowed) — interlock is an add-on, not a hard dependency.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class InterlockResult:
    allowed: bool
    prior_result: str | None = None
    detail: str = ""


class InterlockError(Exception):
    """A run was blocked by the MES interlock. Mapped to HTTP 409."""


CheckFn = Callable[[str, dict], Awaitable[InterlockResult]]


async def _fail_open(_serial: str, _ctx: dict) -> InterlockResult:
    return InterlockResult(allowed=True, detail="no interlock")


class InterlockPort:
    def __init__(self) -> None:
        self._check: CheckFn = _fail_open

    def register(self, check: CheckFn) -> None:
        self._check = check

    async def check(self, serial: str, ctx: dict | None = None) -> InterlockResult:
        return await self._check(serial, ctx or {})

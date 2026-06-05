"""Logs contract (LOGS.md §5). Siblings resolve this via core.get_contract("logs")
and never import the logs package (CORE.md §6.1/§6.3)."""

from __future__ import annotations

from typing import Protocol, TypedDict

from core.services.auth_verify import Principal  # re-export

__all__ = [
    "LEVEL_ORDER",
    "ActionRecord",
    "ErrorRecord",
    "LogsContract",
    "Page",
    "Principal",
]

# Diag levels, lowest -> highest. `level` filters are a *minimum* (LOGS.md §7).
LEVEL_ORDER = ("debug", "info", "warning", "error", "critical")


class ErrorRecord(TypedDict, total=False):
    source: str
    seq: int
    level: str
    subsystem: str
    message: str
    context: dict
    exception: dict | None
    repeat_count: int
    coalesced: bool
    window_start: float | None
    window_end: float | None


class ActionRecord(TypedDict, total=False):
    user: str
    role: str
    action: str
    target: str
    result: str
    detail: dict


class Page(TypedDict):
    items: list[dict]
    next_cursor: str | None
    total: int | None


class LogsContract(Protocol):
    async def record_action(
        self,
        principal: Principal,
        action: str,
        target: str,
        result: str,
        detail: dict | None = None,
    ) -> str: ...

    async def query_errors(
        self,
        since: float | None = None,
        until: float | None = None,
        level: str | None = None,
        subsystem: str | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> Page: ...

    async def query_actions(
        self,
        since: float | None = None,
        until: float | None = None,
        user: str | None = None,
        action: str | None = None,
        result: str | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> Page: ...

"""Transport + deterministic fault injection (INSTRUMENT_LIBRARY.md §7).

Faults live in the transport, not the libraries — a library experiences an injected
fault exactly as real hardware misbehaviour. Deterministic first (`after_n`, `once`,
command-pattern match); a `probability` field MAY be added later without breaking the
schema. The same mechanism serves conformance, health validation, and reproduction.
"""

from __future__ import annotations

import asyncio
import fnmatch
from dataclasses import dataclass, field

from instrumentlib.errors import CommandTimeout, DeviceError, TransportDisconnected


class Transport:
    """Wire abstraction. Real transports (VISA/Modbus/…) subclass this in a later
    phase; IL1 ships the sim + fault wrapper so the base + conformance run headless."""

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def query(self, cmd: str) -> str: raise NotImplementedError
    async def write(self, cmd: str) -> None: raise NotImplementedError


class SimTransport(Transport):
    """`simulated=true` transport (§3): connect is a no-op, reads return plausible
    values, writes are recorded in an inspectable `writes` list."""

    def __init__(self, responses: dict[str, str] | None = None, default_response: str = "1.0"):
        self.connected = False
        self.writes: list[str] = []          # inspectable sim state
        self.responses = responses or {}     # cmd glob -> canned response
        self.default_response = default_response

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def query(self, cmd: str) -> str:
        for pat, val in self.responses.items():
            if fnmatch.fnmatch(cmd, pat):
                return val
        return self.default_response

    async def write(self, cmd: str) -> None:
        self.writes.append(cmd)


@dataclass
class _Rule:
    on: str                       # "read" | "write" | "any"
    match: str                    # command glob
    action: str                   # timeout|disconnect|garbage|delay_ms|error_response
    after_n: int | None = None    # fire from the Nth matching op onward
    once: bool = False            # fire at most once
    value: float | None = None    # delay_ms milliseconds
    payload: str | None = None    # garbage bytes / error_response text
    _count: int = field(default=0)
    _fired: bool = field(default=False)


class FaultPlan:
    def __init__(self, rules: list[dict] | None = None):
        self.rules = [_Rule(**r) for r in (rules or [])]

    def match(self, op: str, cmd: str) -> _Rule | None:
        for r in self.rules:
            if r.on not in (op, "any"):
                continue
            if not fnmatch.fnmatch(cmd, r.match):
                continue
            r._count += 1
            if r.once and r._fired:
                continue
            if r.after_n is not None and r._count < r.after_n:
                continue
            r._fired = True
            return r
        return None


_GARBAGE = "garbage"


class FaultTransport(Transport):
    """Wraps any transport, injecting §7 faults before delegating to the inner one."""

    def __init__(self, inner: Transport, plan: FaultPlan):
        self.inner = inner
        self.plan = plan

    async def connect(self) -> None:
        await self.inner.connect()

    async def disconnect(self) -> None:
        await self.inner.disconnect()

    async def _apply(self, op: str, cmd: str):
        rule = self.plan.match(op, cmd)
        if rule is None:
            return None
        a = rule.action
        if a == "timeout":
            raise CommandTimeout("injected timeout", detail=cmd)
        if a == "disconnect":
            await self.inner.disconnect()
            raise TransportDisconnected("injected disconnect", detail=cmd)
        if a == "error_response":
            raise DeviceError("injected device error", detail=rule.payload)
        if a == "delay_ms":
            await asyncio.sleep((rule.value or 0) / 1000.0)   # slow device, then proceed
            return None
        if a == "garbage":
            return (_GARBAGE, rule.payload if rule.payload is not None else "\xff\x00")
        return None

    async def query(self, cmd: str) -> str:
        injected = await self._apply("read", cmd)
        if isinstance(injected, tuple) and injected[0] == _GARBAGE:
            return injected[1]                     # malformed response instead of the real read
        return await self.inner.query(cmd)

    async def write(self, cmd: str) -> None:
        await self._apply("write", cmd)
        await self.inner.write(cmd)

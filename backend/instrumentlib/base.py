"""InstrumentBase — the fat base (INSTRUMENT_LIBRARY.md §3).

Every cross-cutting behaviour lives here, once: per-instance lock, connection state
machine + backoff, fail-fast on a dead link (never queue), per-command timeout,
automatic diagnostics emit, simulation, fault injection (via the transport), and the
mandatory `safe_state`/`emergency_disable` surface (fanned out in parallel). A
library adds only device-specific knowledge and NEVER reimplements any of this.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from instrumentlib.errors import (
    CommandTimeout,
    IdentityMismatch,
    InstrumentError,
    NotConnected,
    NotSupported,
    TransportDisconnected,
    describe_exc,
)
from instrumentlib.transport import FaultPlan, FaultTransport, SimTransport, Transport

# Registry of live instances for the platform-level emergency fan-out (§3).
_INSTANCES: "list[InstrumentBase]" = []


class InstrumentBase:
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAULTED = "faulted"

    EXPECTED_IDN: str | None = None       # library sets this; re-verified on reconnect

    def __init__(self, instance_id: str, *, transport: Transport | None = None,
                 simulated: bool = False, params: dict | None = None,
                 fault_plan: list[dict] | None = None,
                 timeout_s: float = 5.0, on_command: Callable[[dict], None] | None = None,
                 backoff_start_s: float = 1.0, backoff_cap_s: float = 30.0):
        self.instance_id = instance_id
        self.simulated = simulated
        self.params = params or {}       # connection params; a real library builds its transport from these
        self._timeout = timeout_s
        self._backoff_start = backoff_start_s
        self._backoff_cap = backoff_cap_s
        self._on_command = on_command
        self._lock = asyncio.Lock()
        self.state = self.DISCONNECTED
        inner = transport or SimTransport()
        self.transport: Transport = FaultTransport(inner, FaultPlan(fault_plan)) if fault_plan else inner
        self._recon_task: asyncio.Task | None = None
        _INSTANCES.append(self)

    # ---- library hooks (override) -----------------------------------------

    async def identify(self) -> str:
        """Return the device identity (e.g. `*IDN?`). Override in the library."""
        return self.EXPECTED_IDN or ""

    async def on_reconnect(self) -> None:
        """Called after a physical reconnect: re-verify identity, re-apply safe state.
        Restoring prior setpoints is allowed only if the library declares it safe."""
        idn = await self.identify()
        if self.EXPECTED_IDN and self.EXPECTED_IDN not in idn:
            raise IdentityMismatch(f"identity mismatch: {idn!r}", instance_id=self.instance_id)

    async def safe_state(self) -> None:
        """Drive the instrument to a known-safe state. Override (mandatory in practice)."""

    async def emergency_disable(self) -> None:
        """Cut all outputs NOW. Override. The platform fans this out in parallel."""

    # ---- connection state machine (§3) ------------------------------------

    async def connect(self) -> None:
        self.state = self.CONNECTING
        try:
            await self.transport.connect()
        except Exception as exc:  # noqa: BLE001
            self.state = self.DISCONNECTED
            raise InstrumentError(f"connect failed: {exc}", instance_id=self.instance_id) from exc
        self.state = self.CONNECTED
        self._emit_state("connected")

    async def disconnect(self) -> None:
        if self._recon_task and not self._recon_task.done():
            self._recon_task.cancel()
        await self.transport.disconnect()
        self.state = self.DISCONNECTED

    def _begin_reconnect(self) -> None:
        if self._recon_task and not self._recon_task.done():
            return
        self.state = self.RECONNECTING
        self._emit_state("reconnecting")
        self._recon_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        delay = self._backoff_start
        while self.state == self.RECONNECTING:
            try:
                await self.transport.connect()
                await self.on_reconnect()           # identity re-verify + safe state
                await self.safe_state()
                self.state = self.CONNECTED
                self._emit_state("connected")
                return
            except IdentityMismatch:
                self.state = self.FAULTED           # hard stop — do not resume (§6.3)
                self._emit_state("faulted")
                return
            except Exception:  # noqa: BLE001 — link still down, back off and retry
                await asyncio.sleep(min(delay, self._backoff_cap))
                delay = min(delay * 2, self._backoff_cap)

    # ---- the one call path every consumer uses (§3) -----------------------

    async def invoke(self, method: str, *args, **kwargs):
        """Run a capability method with lock + fail-fast + timeout + diagnostics.
        The variable engine and `capability.request` call THIS, never the raw method."""
        async with self._lock:
            if self.state != self.CONNECTED:
                raise NotConnected(f"{self.instance_id} not connected ({self.state})",
                                   instance_id=self.instance_id, method=method)
            fn = getattr(self, method, None)
            if not callable(fn):
                raise NotSupported(f"no method '{method}'", instance_id=self.instance_id, method=method)
            t0 = time.time()
            outcome, err = "ok", None
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), self._timeout)
            except asyncio.TimeoutError as e:
                outcome, err = "timeout", CommandTimeout(f"command timed out after {self._timeout:g}s",
                                                         instance_id=self.instance_id, method=method)
                raise err from e
            except TransportDisconnected as e:
                outcome, err = "disconnected", e
                self._begin_reconnect()              # start backoff loop; caller fails fast
                raise NotConnected(f"link dropped mid-command: {type(e).__name__}: {describe_exc(e)}",
                                   instance_id=self.instance_id, method=method) from e
            except InstrumentError as e:
                outcome, err = "error", e
                raise
            except Exception as e:  # noqa: BLE001 — unexpected library error -> structured
                outcome, err = "error", InstrumentError(f"{type(e).__name__}: {describe_exc(e)}",
                                                    instance_id=self.instance_id, method=method)
                raise err from e
            finally:
                self._emit_command(method, args, (time.time() - t0) * 1000.0, outcome, err)

    # ---- diagnostics (zero per-library effort, §3) ------------------------

    def _provenance(self) -> dict:
        decl = getattr(type(self), "_declaration", {}) or {}
        return {k: decl.get(k) for k in ("library_id", "library_version", "generated_by")}

    def _emit_command(self, method, args, elapsed_ms, outcome, err) -> None:
        if self._on_command is None:
            return
        rec = {"kind": "command", "instance_id": self.instance_id, "method": method,
               "args": repr(args)[:120], "elapsed_ms": round(elapsed_ms, 2),
               "outcome": outcome, "error": err.as_dict() if isinstance(err, InstrumentError) else None,
               **self._provenance()}
        try:
            self._on_command(rec)
        except Exception:  # noqa: BLE001 — diagnostics must never break a command
            pass

    def _emit_state(self, state: str) -> None:
        if self._on_command is None:
            return
        try:
            self._on_command({"kind": "state", "instance_id": self.instance_id,
                              "state": state, **self._provenance()})
        except Exception:  # noqa: BLE001
            pass


async def emergency_disable_all() -> list:
    """Cut outputs on every registered instance in parallel (§3, §12.6)."""
    return await asyncio.gather(*(i.emergency_disable() for i in _INSTANCES),
                                return_exceptions=True)


def registered_instances() -> "list[InstrumentBase]":
    return list(_INSTANCES)


def _reset_instances() -> None:      # test hygiene
    _INSTANCES.clear()

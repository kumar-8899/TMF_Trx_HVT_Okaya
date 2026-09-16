"""VISA transport (real hardware). Lazy-imports pyvisa so sim + conformance run
without it. pyvisa is blocking, so every wire op runs in a thread executor — never
stall the event loop (mirrors the delay_ms fault concern in INSTRUMENT_LIBRARY §7)."""

from __future__ import annotations

import asyncio

from instrumentlib.errors import TransportDisconnected
from instrumentlib.transport import Transport


class VisaTransport(Transport):
    def __init__(self, resource: str, *, timeout_ms: int = 5000,
                 read_termination: str = "\n", write_termination: str = "\n"):
        self.resource = resource
        self.timeout_ms = timeout_ms
        self.read_termination = read_termination
        self.write_termination = write_termination
        self._rm = None
        self._inst = None

    async def _run(self, fn, *a):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *a)

    async def connect(self) -> None:
        import pyvisa  # lazy — only when talking to real hardware

        def _open():
            rm = pyvisa.ResourceManager()
            inst = rm.open_resource(self.resource)
            inst.timeout = self.timeout_ms
            inst.read_termination = self.read_termination
            inst.write_termination = self.write_termination
            return rm, inst

        try:
            self._rm, self._inst = await self._run(_open)
        except Exception as exc:  # noqa: BLE001 — surface as a structured disconnect
            raise TransportDisconnected(f"VISA open failed: {exc}", detail=self.resource) from exc

    async def disconnect(self) -> None:
        if self._inst is not None:
            try:
                await self._run(self._inst.close)
            except Exception:  # noqa: BLE001
                pass
        self._inst = self._rm = None

    async def query(self, cmd: str) -> str:
        if self._inst is None:
            raise TransportDisconnected("VISA not connected", detail=cmd)
        try:
            return (await self._run(self._inst.query, cmd)).strip()
        except Exception as exc:  # noqa: BLE001 — a timeout/IO error is a lost link
            raise TransportDisconnected(f"VISA query failed: {exc}", detail=cmd) from exc

    async def write(self, cmd: str) -> None:
        if self._inst is None:
            raise TransportDisconnected("VISA not connected", detail=cmd)
        try:
            await self._run(self._inst.write, cmd)
        except Exception as exc:  # noqa: BLE001 — a timeout/IO error is a lost link, same as query()
            raise TransportDisconnected(f"VISA write failed: {exc}", detail=cmd) from exc

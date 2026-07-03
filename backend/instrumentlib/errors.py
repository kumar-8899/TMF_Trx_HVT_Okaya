"""Structured instrument errors (INSTRUMENT_LIBRARY.md §12.5).

A corrupted/implausible reading or a device fault MUST surface as one of these,
never as a value — a silently wrong number poisons a PASS/FAIL verdict. Every
error is RAG-shaped (`as_dict`) so it drops into a diagnostics record.
"""

from __future__ import annotations


class InstrumentError(Exception):
    """Base for every instrument-layer error."""

    def __init__(self, message: str, *, instance_id: str | None = None,
                 method: str | None = None, code: str | None = None, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.instance_id = instance_id
        self.method = method
        self.code = code
        self.detail = detail

    def as_dict(self) -> dict:
        return {"type": type(self).__name__, "message": self.message,
                "instance_id": self.instance_id, "method": self.method,
                "code": self.code, "detail": self.detail}


class NotConnected(InstrumentError):
    """A command was issued while the link was not `connected` (fail-fast, §3)."""


class NotSupported(InstrumentError):
    """A capability method the library does not implement (§2.3)."""


class DeviceError(InstrumentError):
    """A device-level error (SCPI error queue / Modbus exception), §4.4."""


class CommandTimeout(InstrumentError):
    """A command exceeded its per-command budget (§3). Never a hang."""


class GarbageResponse(InstrumentError):
    """A malformed / implausible reading (§7 garbage; error-not-value rule)."""


class IdentityMismatch(InstrumentError):
    """`*IDN?` did not match after reconnect (§6.3) — instance is faulted."""


class TransportDisconnected(InstrumentError):
    """The transport lost the link mid-exchange (raised by the transport, §7)."""

"""Database MES transport — inbound gate + outbound publish against customer databases.

Composes `DbInbound` (read-only status lookup) and `DbOutbound` (one-table result write). The two are
independent: each has its own server connection (outbound may reuse the inbound one via
`same_as_inbound`), and either can be unconfigured while the other works.
"""

from __future__ import annotations

import copy

from core.services.interlock import InterlockResult
from modules.mes.providers.db_inbound import DbInbound
from modules.mes.providers.db_outbound import DbOutbound

# connection keys that identify a server (a stored password is only reused for the same server)
CONN_KEYS = ("provider", "host", "port", "user", "password", "odbc_driver", "path")


def resolve(cfg: dict) -> dict:
    """Effective {inbound, outbound}: outbound with same_as_inbound borrows the inbound connection."""
    cfg = copy.deepcopy(cfg or {})
    inbound, outbound = cfg.get("inbound") or {}, cfg.get("outbound") or {}
    if outbound.get("same_as_inbound"):
        outbound["connection"] = dict(inbound.get("connection") or {})
    return {"inbound": inbound, "outbound": outbound}


class DatabaseProvider:
    def __init__(self, db_config: dict, *, on_missing: str = "block", on_error: str = "block") -> None:
        eff = resolve(db_config)
        self.inbound = DbInbound(eff["inbound"], on_missing=on_missing, on_error=on_error)
        self.outbound = DbOutbound(eff["outbound"])

    async def check_upstream(self, serial: str) -> InterlockResult:
        return await self.inbound.check(serial)

    async def publish_result(self, serial: str, result: str, payload: dict) -> None:
        await self.outbound.publish({**payload, "serial_no": serial, "result": result})

    def describe(self) -> dict:
        return {"kind": "database", "inbound": self.inbound.describe(), "outbound": self.outbound.describe()}

    def dispose(self) -> None:
        self.inbound.dispose()
        self.outbound.dispose()

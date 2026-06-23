"""config `default` variant — instrument registry + transport catalog (CONFIG).

Instruments are operator-editable runtime data → stored as append-overwrite DB
records (type `instrument`), not app.json. `instrument.test` is dispatched to
LabVIEW (it owns the driver); offline bridge degrades to `unavailable`, never
hangs (mirrors the health seam, PRINCIPLES §0).
"""

from __future__ import annotations

import asyncio
import re
import time

from core.framework.contract import CoreServices
from modules.config import transports as tcat
from modules.config.api import build_router

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TEST_TIMEOUT_S = 8.0


class ConfigError(Exception):
    """Bad instrument input (duplicate id, unknown transport, missing field)."""


class DefaultConfig:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.router = build_router(self)

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultConfig":
        return cls(core, config)

    async def init(self) -> None: pass
    async def start(self) -> None: pass
    async def stop(self) -> None: pass

    # --- transport catalog -------------------------------------------------

    def transports(self) -> list[dict]:
        return tcat.TRANSPORTS

    # --- instruments (CRUD) ------------------------------------------------

    async def list_instruments(self) -> list[dict]:
        rows = await self.core.db.repo.query("instrument")
        return [r["data"] for r in rows]

    async def get_instrument(self, iid: str) -> dict | None:
        rec = await self.core.db.repo.get("instrument", iid)
        return rec["data"] if rec else None

    def _normalise(self, body: dict) -> dict:
        transport = body.get("transport")
        if tcat.get(transport) is None:
            raise ConfigError(f"unknown transport '{transport}'")
        params = body.get("params") or {}
        missing = tcat.missing_required(transport, params)
        if missing:
            raise ConfigError(f"missing required field(s): {', '.join(missing)}")
        return {
            "id": body["id"],
            "label": body.get("label") or body["id"],
            "model": body.get("model", ""),
            "transport": transport,
            "params": params,
            "address": tcat.render_address(transport, params),
            "family": body.get("family", ""),
            "capabilities": body.get("capabilities", []) or [],
            "enabled": bool(body.get("enabled", True)),
            "updated_ts": time.time(),
        }

    async def create_instrument(self, body: dict) -> dict:
        iid = (body.get("id") or "").strip()
        if not _ID_RE.match(iid):
            raise ConfigError("id must match ^[a-z][a-z0-9_]{0,63}$")
        if await self.get_instrument(iid):
            raise ConfigError(f"instrument '{iid}' already exists")
        rec = self._normalise({**body, "id": iid})
        await self.core.db.repo.put("instrument", rec, id=iid, summary=rec["label"])
        self.core.diag.info("config", "instrument created", instrument_id=iid, transport=rec["transport"])
        return rec

    async def update_instrument(self, iid: str, body: dict) -> dict:
        if not await self.get_instrument(iid):
            raise ConfigError(f"no instrument '{iid}'")
        rec = self._normalise({**body, "id": iid})
        await self.core.db.repo.put("instrument", rec, id=iid, summary=rec["label"])
        self.core.diag.info("config", "instrument updated", instrument_id=iid)
        return rec

    async def delete_instrument(self, iid: str) -> bool:
        if not await self.get_instrument(iid):
            return False
        await self.core.db.repo.delete_id("instrument", iid)
        self.core.diag.info("config", "instrument deleted", instrument_id=iid)
        return True

    # --- test connection (LabVIEW owns the I/O) ----------------------------

    async def test_connection(self, body: dict) -> dict:
        """Probe an instrument via LabVIEW. Accepts a saved id OR an ad-hoc
        {transport, params}. Honest verdict: unavailable when the bridge is down."""
        if body.get("id"):
            inst = await self.get_instrument(body["id"])
            if inst is None:
                raise ConfigError(f"no instrument '{body['id']}'")
            transport, params = inst["transport"], inst["params"]
        else:
            transport, params = body.get("transport"), body.get("params") or {}
            if tcat.get(transport) is None:
                raise ConfigError(f"unknown transport '{transport}'")
        address = tcat.render_address(transport, params)
        payload = {"transport": transport, "params": params, "address": address}

        if self.core.bridge is None or not self.core.bridge.online:
            return {"ok": False, "status": "unavailable", "address": address,
                    "detail": "LabVIEW bridge offline — cannot probe the device."}
        try:
            reply = await asyncio.wait_for(
                self.core.bridge.request("instrument.test", payload), _TEST_TIMEOUT_S)
        except asyncio.TimeoutError:
            return {"ok": False, "status": "timeout", "address": address,
                    "detail": f"no answer within {int(_TEST_TIMEOUT_S)} s"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "error", "address": address, "detail": str(exc)}
        ok = bool(reply.get("ok", reply.get("status") == "pass"))
        return {"ok": ok, "status": reply.get("status", "pass" if ok else "fail"),
                "address": address, "identity": reply.get("identity") or reply.get("idn"),
                "detail": reply.get("detail") or reply.get("summary", "")}

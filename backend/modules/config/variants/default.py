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
from instrumentlib.registry import REGISTRY
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
        # Every instrument declares one execution owner (INSTRUMENT_LIBRARY §0):
        # python-owned = reached via the variable engine / a library; labview-owned =
        # reached via LabVIEW over the bridge (transport profile). Disjoint by design.
        owner = body.get("owner", "labview")
        common = {
            "id": body["id"],
            "label": body.get("label") or body["id"],
            "model": body.get("model", ""),
            "owner": owner,
            "family": body.get("family", ""),
            "capabilities": body.get("capabilities", []) or [],
            "enabled": bool(body.get("enabled", True)),
            "updated_ts": time.time(),
        }
        if owner == "python":
            return {**common, **self._normalise_python(body)}
        return {**common, **self._normalise_labview(body)}

    def _normalise_labview(self, body: dict) -> dict:
        transport = body.get("transport")
        if tcat.get(transport) is None:
            raise ConfigError(f"unknown transport '{transport}'")
        params = body.get("params") or {}
        missing = tcat.missing_required(transport, params)
        if missing:
            raise ConfigError(f"missing required field(s): {', '.join(missing)}")
        return {"transport": transport, "params": params,
                "address": tcat.render_address(transport, params)}

    def _normalise_python(self, body: dict) -> dict:
        library = body.get("library")
        entry = REGISTRY.get(library)
        if entry is None:
            known = ", ".join(sorted(REGISTRY)) or "none loaded"
            raise ConfigError(f"unknown library '{library}' (known: {known})")
        params = body.get("params") or {}
        conn = entry.get("connection_params") or {}
        missing = [k for k, spec in conn.items()
                   if isinstance(spec, dict) and "default" not in spec and k not in params]
        if missing:
            raise ConfigError(f"missing required param(s): {', '.join(missing)}")
        return {"library": library, "params": params,
                "simulated": bool(body.get("simulated", False)),
                "address": str(params.get("resource", ""))}

    async def python_instruments(self) -> list[dict]:
        """Owner=python instruments, in the shape the variables module builds from
        (INSTRUMENT_LIBRARY §5.2). The variable engine consumes THIS at startup."""
        rows = await self.list_instruments()
        return [{"id": r["id"], "library": r["library"], "params": r.get("params", {}),
                 "simulated": r.get("simulated", False)}
                for r in rows if r.get("owner") == "python" and r.get("enabled", True) and r.get("library")]

    async def create_instrument(self, body: dict) -> dict:
        iid = (body.get("id") or "").strip()
        if not _ID_RE.match(iid):
            raise ConfigError("id must match ^[a-z][a-z0-9_]{0,63}$")
        if await self.get_instrument(iid):
            raise ConfigError(f"instrument '{iid}' already exists")
        rec = self._normalise({**body, "id": iid})
        await self.core.db.repo.put("instrument", rec, id=iid, summary=rec["label"])
        self.core.diag.info("config", "instrument created", instrument_id=iid,
                            owner=rec["owner"], via=rec.get("library") or rec.get("transport"))
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
        """Probe an instrument. LabVIEW-owned → dispatched to LabVIEW over the bridge.
        Python-owned → report the live instance state from the variable engine (it
        connects at startup); honest verdict, never a hang."""
        saved = await self.get_instrument(body["id"]) if body.get("id") else None
        owner = (saved or body).get("owner", "labview")
        if owner == "python":
            return self._python_test(saved or body)
        if saved:
            transport, params = saved["transport"], saved["params"]
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

    def _python_test(self, inst: dict) -> dict:
        address = str((inst.get("params") or {}).get("resource", ""))
        get = getattr(self.core, "get_contract", None)
        try:
            var = get("variables") if get else None
        except KeyError:
            var = None
        if var is None:
            return {"ok": False, "status": "unavailable", "address": address,
                    "detail": "variable engine not loaded."}
        st = {s["id"]: s for s in var.instance_status()}.get(inst.get("id"))
        if st is None:
            return {"ok": False, "status": "unavailable", "address": address,
                    "detail": "not loaded yet — Python instruments build at startup; restart to apply."}
        connected = st["state"] == "connected"
        return {"ok": connected, "status": "pass" if connected else "fail",
                "address": address, "identity": f"{st.get('library')}{' · sim' if st.get('simulated') else ''}",
                "detail": f"instance state: {st['state']}"}

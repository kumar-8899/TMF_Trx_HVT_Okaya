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
from datetime import datetime, timedelta

from core.framework.contract import CoreServices
from instrumentlib.registry import REGISTRY
from modules.config import transports as tcat
from modules.config.api import build_router

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TEST_TIMEOUT_S = 8.0
_SHIFT_ID = "shift"
_BARCODE_ID = "barcode"


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


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
            "stations": self._normalise_stations(body),
            "enabled": bool(body.get("enabled", True)),
            "updated_ts": time.time(),
        }
        if owner == "python":
            return {**common, **self._normalise_python(body)}
        return {**common, **self._normalise_labview(body)}

    def _normalise_stations(self, body: dict) -> list[str]:
        """Sockets this instrument serves (MULTI_STATION.md §4.3). Singular `station`
        migrates to a one-element list; absent -> every socket (a shared instrument).
        Each id must be a configured station."""
        app_stations = list(getattr(self.core, "stations", None) or [self.core.station])
        stations = body.get("stations")
        if not stations:
            stations = [body["station"]] if body.get("station") else list(app_stations)
        bad = [s for s in stations if s not in app_stations]
        if bad:
            raise ConfigError(f"unknown station(s) {bad}; app has {app_stations}")
        return list(stations)

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
        # capabilities come from the library declaration, not free-typed input (the library
        # is the source of truth; a composite instrument declares several).
        return {"library": library, "params": params,
                "capabilities": list(entry.get("capabilities", [])),
                "simulated": bool(body.get("simulated", False)),
                "address": str(params.get("resource", ""))}

    async def python_instruments(self) -> list[dict]:
        """Owner=python instruments, in the shape the variables module builds from
        (INSTRUMENT_LIBRARY §5.2). The variable engine consumes THIS at startup."""
        rows = await self.list_instruments()
        return [{"id": r["id"], "library": r["library"], "params": r.get("params", {}),
                 "simulated": r.get("simulated", False),
                 "stations": r.get("stations") or list(getattr(self.core, "stations", None)
                                                       or [self.core.station])}
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

    # --- shifts (business day + shift labels) ------------------------------
    # Locked model: shifts TILE 24h contiguously (each runs to the next shift's
    # start; the last wraps past midnight). The business day rolls at the FIRST
    # shift's start; an overnight shift belongs to the calendar date it started on.
    # A run is assigned by its START time (INSTRUMENT/analytics contract).

    async def get_shift_config(self) -> dict:
        rec = await self.core.db.repo.get("shift_config", _SHIFT_ID)
        data = rec["data"] if rec else {}
        return {"enabled": bool(data.get("enabled", False)), "shifts": data.get("shifts", []) or []}

    async def set_shift_config(self, body: dict) -> dict:
        enabled = bool(body.get("enabled", False))
        shifts = body.get("shifts") or []
        cleaned = []
        seen = set()
        for i, s in enumerate(shifts):
            label = (s.get("label") or "").strip()
            start = (s.get("start") or "").strip()
            if not label:
                raise ConfigError(f"shift #{i + 1}: label required")
            if not _HHMM_RE.match(start):
                raise ConfigError(f"shift '{label}': start must be HH:MM (24h)")
            if start in seen:
                raise ConfigError(f"duplicate shift start time {start}")
            seen.add(start)
            cleaned.append({"label": label, "start": start})
        if enabled and not cleaned:
            raise ConfigError("enable shifts requires at least one shift")
        cleaned.sort(key=lambda s: _to_min(s["start"]))   # order by start; first = day boundary
        rec = {"enabled": enabled, "shifts": cleaned, "updated_ts": time.time()}
        await self.core.db.repo.put("shift_config", rec, id=_SHIFT_ID, summary=f"{len(cleaned)} shift(s)")
        self.core.diag.info("config", "shift config updated", enabled=enabled, shifts=len(cleaned))
        return rec

    async def shift_for(self, ts: float) -> dict:
        """Resolve a timestamp to {enabled, business_day (YYYY-MM-DD), shift_label,
        index}. business_day rolls at the first shift's start; disabled/none ->
        business_day is the calendar date and shift_label is None."""
        dt = datetime.fromtimestamp(ts)
        cal = dt.strftime("%Y-%m-%d")
        cfg = await self.get_shift_config()
        shifts = cfg["shifts"]
        if not cfg["enabled"] or not shifts:
            return {"enabled": False, "business_day": cal, "shift_label": None, "index": None}
        starts = [_to_min(s["start"]) for s in shifts]     # already sorted on save
        boundary = starts[0]
        tod = dt.hour * 60 + dt.minute
        business_day = (dt - timedelta(days=1)).strftime("%Y-%m-%d") if tod < boundary else cal
        if tod < boundary:
            idx = len(shifts) - 1                          # overnight shift that wrapped past midnight
        else:
            idx = max(i for i, sm in enumerate(starts) if sm <= tod)
        return {"enabled": True, "business_day": business_day,
                "shift_label": shifts[idx]["label"], "index": idx, "start": shifts[idx]["start"]}

    async def current_shift(self) -> dict:
        return await self.shift_for(time.time())

    # --- barcode (structure + recipe-id extraction) ------------------------
    # A barcode is a fixed total length divided into named parts, each an
    # {start, length} slice; one part is designated the recipe-id part. Global
    # to the app (a labeling scheme, not per-socket wiring like Instruments).

    async def get_barcode_config(self) -> dict:
        rec = await self.core.db.repo.get("barcode_config", _BARCODE_ID)
        data = rec["data"] if rec else {}
        return {"enabled": bool(data.get("enabled", False)),
                "length": int(data.get("length", 0)),
                "parts": data.get("parts", []) or [],
                "recipe_part": data.get("recipe_part"),
                # Scan-to-submit must be an explicit opt-in (framework-fix-prompt-2.md
                # Issue 1) — a real barcode scanner appends Enter to every scan, so an
                # unconditional Enter-starts-the-run default removes an operator's chance
                # to review what was scanned before hardware energizes. Default False.
                "submit_on_enter": bool(data.get("submit_on_enter", False))}

    async def set_barcode_config(self, body: dict) -> dict:
        enabled = bool(body.get("enabled", False))
        length = int(body.get("length") or 0)
        if length < 1:
            raise ConfigError("length must be >= 1")
        cleaned = []
        seen = set()
        for i, p in enumerate(body.get("parts") or []):
            name = (p.get("name") or "").strip()
            if not name:
                raise ConfigError(f"part #{i + 1}: name required")
            if name in seen:
                raise ConfigError(f"duplicate part name '{name}'")
            start, plen = int(p.get("start", -1)), int(p.get("length", 0))
            if start < 0:
                raise ConfigError(f"part '{name}': start must be >= 0")
            if plen < 1:
                raise ConfigError(f"part '{name}': length must be >= 1")
            if start + plen > length:
                raise ConfigError(f"part '{name}': exceeds total barcode length ({length})")
            seen.add(name)
            cleaned.append({"name": name, "start": start, "length": plen})
        recipe_part = body.get("recipe_part")
        if enabled:
            if not cleaned:
                raise ConfigError("enable barcode requires at least one part")
            if not recipe_part or recipe_part not in seen:
                raise ConfigError("recipe_part must reference a configured part")
        submit_on_enter = bool(body.get("submit_on_enter", False))
        rec = {"enabled": enabled, "length": length, "parts": cleaned,
               "recipe_part": recipe_part, "submit_on_enter": submit_on_enter,
               "updated_ts": time.time()}
        await self.core.db.repo.put("barcode_config", rec, id=_BARCODE_ID,
                                    summary=f"{len(cleaned)} part(s)" + (" · enabled" if enabled else ""))
        self.core.diag.info("config", "barcode config updated", enabled=enabled, parts=len(cleaned))
        return rec

    async def resolve_recipe_from_barcode(self, barcode: str) -> dict:
        """{"ok": True, "recipe_id", "parts": {name: value}} or {"ok": False, "error"}.
        A dict envelope, not a raised exception — this is called across the module
        boundary (by `runs`) and there's no established pattern here for one module's
        exception classes propagating through another's. Does NOT verify the extracted
        recipe id actually exists (a later fetch, e.g. LabVIEW's recipe.fetch, does)."""
        cfg = await self.get_barcode_config()
        if not cfg["enabled"]:
            return {"ok": False, "error": "barcode acquisition not enabled"}
        barcode = (barcode or "").strip()
        if not barcode:
            return {"ok": False, "error": "empty barcode"}
        if len(barcode) != cfg["length"]:
            return {"ok": False, "error": f"barcode length {len(barcode)} != configured {cfg['length']}"}
        recipe_part = cfg.get("recipe_part")
        parts_by_name = {p["name"]: p for p in cfg["parts"]}
        if not recipe_part or recipe_part not in parts_by_name:
            return {"ok": False, "error": "no recipe part configured"}
        values = {p["name"]: barcode[p["start"]:p["start"] + p["length"]] for p in cfg["parts"]}
        recipe_id = values.get(recipe_part, "").strip()
        if not recipe_id:
            return {"ok": False, "error": "extracted recipe id is empty"}
        return {"ok": True, "recipe_id": recipe_id, "parts": values}

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
                self.core.bridge.request("instrument.test", payload, station=self.core.station),
                _TEST_TIMEOUT_S)
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

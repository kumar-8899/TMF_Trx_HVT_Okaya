"""MES `default` variant — fills the core.interlock port, publishes on run-finish.

Two transports behind one seam: **folder** (file handoff) and **database** (inbound status lookup in a
customer table; outbound one-row-per-run write into a single table). Provider, gate/publish switches and
the database settings are all editable at runtime (Config → MES) and persisted as records
(`mes_setting`, `mes_db_config`); `app.json` supplies only the defaults.

Outbound is INSTANT and LOUD: the result is sent the moment `run-finished` arrives. If it fails there is
no queue and no silent retry — a `mes_push` status record keeps the failure until the operator presses
Retry (the row is rebuilt from the run record) or Dismiss, and the UI prompts about it on every screen.
"""

from __future__ import annotations

import asyncio
import copy
import time

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services import dbconn
from core.services.interlock import InterlockResult
from modules.mes.api import build_router
from modules.mes.providers import db_schema as S
from modules.mes.providers import make_provider
from modules.mes.providers.database import CONN_KEYS
from modules.mes.providers.db_inbound import DbInbound
from modules.mes.providers.db_outbound import DbOutbound

_SETTING_ID = "mes"
_DB_ID = "mes_db"
_PUSH = "mes_push"
_PROVIDERS = ("folder", "database")
_POLICY = ("block", "allow")


def _redact(db: dict) -> dict:
    """Copy with every password removed (+ has_password flags). Passwords never leave the station."""
    out = copy.deepcopy(db or {})
    for side in ("inbound", "outbound"):
        conn = (out.get(side) or {}).get("connection")
        if isinstance(conn, dict):
            conn["has_password"] = bool(conn.pop("password", None))
    return out


def _merge_side(old: dict, new: dict) -> dict:
    """Merge one direction's draft over the stored one. The connection is replaced by the draft's, but a
    blank password keeps the stored one (only when it is still the same server)."""
    merged = {**old, **{k: v for k, v in new.items() if k != "connection"}}
    if "connection" in new:
        nc = {k: v for k, v in (new["connection"] or {}).items() if k != "has_password"}
        oc = old.get("connection") or {}
        if not nc.get("password"):
            nc.pop("password", None)
            if oc.get("password") and _same_server(oc, nc):
                nc["password"] = oc["password"]
        merged["connection"] = nc
    return merged


def _same_server(a: dict, b: dict) -> bool:
    """A stored password is only ever re-used for the SAME server (never sent to a different host)."""
    return all(str(a.get(k) or "") == str(b.get(k) or "")
               for k in ("provider", "host", "port", "user", "path"))


class DefaultMes:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.stage = config.get("stage", core.station)
        self.provider_kind = config.get("provider", "folder")
        gate = config.get("gate", {}) or {}
        publish = config.get("publish", {}) or {}
        self.on_missing = gate.get("on_missing", "block")
        self.on_error = gate.get("on_error", "block")
        # runtime-toggleable flags (config = the default; Config → MES overrides)
        self.gate_enabled = bool(gate.get("enabled", False))
        self.publish_enabled = bool(publish.get("enabled", False))
        self.db_config: dict = copy.deepcopy(config.get("database", {}) or {})
        self.provider = make_provider(self.provider_kind, config, on_missing=self.on_missing,
                                      on_error=self.on_error, db_config=self.db_config)
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> DefaultMes:
        return cls(core, config)

    # --- lifecycle ---------------------------------------------------------------------------

    async def init(self) -> None:
        rec = await self.core.db.repo.get("mes_setting", _SETTING_ID)
        if rec:
            d = rec["data"]
            self.gate_enabled = bool(d.get("gate_enabled", self.gate_enabled))
            self.publish_enabled = bool(d.get("publish_enabled", self.publish_enabled))
            if d.get("provider") in _PROVIDERS:
                self.provider_kind = d["provider"]
            if d.get("on_missing") in _POLICY:
                self.on_missing = d["on_missing"]
            if d.get("on_error") in _POLICY:
                self.on_error = d["on_error"]
        dbrec = await self.core.db.repo.get("mes_db_config", _DB_ID)
        if dbrec:
            self.db_config = dbrec["data"]
        self._rebuild_provider()
        if self.core.interlock is not None:        # fill the port so the runs module can gate on us
            self.core.interlock.register(self.check)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        self._dispose_provider()

    def _dispose_provider(self) -> None:
        d = getattr(self.provider, "dispose", None)
        if d:
            d()

    def _rebuild_provider(self) -> None:
        self._dispose_provider()
        self.provider = make_provider(self.provider_kind, self.config, on_missing=self.on_missing,
                                      on_error=self.on_error, db_config=self.db_config)

    async def health(self) -> Health:
        failed = len(await self._failed())
        detail = f"{self.provider_kind} · gate={self.gate_enabled} publish={self.publish_enabled}"
        if failed:
            return Health(status=HealthStatus.DEGRADED,
                          detail=f"{failed} MES result(s) NOT delivered — needs attention · {detail}")
        return Health(status=HealthStatus.OK, detail=detail)

    # --- interlock port (called by runs at run start) -----------------------------------------

    async def check(self, serial: str, ctx: dict) -> InterlockResult:
        if not self.gate_enabled or not serial:
            return InterlockResult(allowed=True, detail="gate disabled")
        try:
            res = await self.provider.check_upstream(serial)
        except Exception as exc:  # noqa: BLE001 — a gate must answer; folder I/O errors included
            res = InterlockResult(allowed=self.on_error == "allow",
                                  detail=f"MES check failed: {dbconn.short_error(exc)}")
            self.core.diag.error("mes", "interlock check failed", serial=serial, error=str(exc))
        log = self.core.diag.info if res.allowed else self.core.diag.warning
        log("mes", "interlock check", serial=serial, allowed=res.allowed,
            prior=res.prior_result, detail=res.detail)
        return res

    async def publish(self, serial: str, result: str, payload: dict) -> None:
        """Send one result. RAISES on failure (the run-finished handler turns that into an alert)."""
        if not self.publish_enabled or not serial:
            return
        await self.provider.publish_result(serial, result, payload)
        self.core.diag.info("mes", "result published", serial=serial, result=result, stage=self.stage)

    # --- run-finished -> publish (instant, loud on failure) ------------------------------------

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        if etype != "run-finished" or not self.publish_enabled:
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id")
        if not run_id:
            return
        serial = ""
        try:
            row = await self._build_row(run_id, body, payload.get("ts"))
            serial = row["serial_no"]
            if not serial:
                return
            await self.publish(serial, row["result"], row)
            await self.core.db.repo.delete_id(_PUSH, run_id)          # a stale failure for this run is moot
        except Exception as exc:  # noqa: BLE001 — never lose a delivery failure
            await self._record_failure(run_id, serial, body.get("result"), exc)

    async def _build_row(self, run_id: str, body: dict, event_ts) -> dict:
        """The MES row for one run: report-header fields (db_schema.MES_FIELDS) + `stage`.
        Used by the live push AND by Retry (event data absent -> everything comes from the run record)."""
        rec = await self.core.db.repo.get("run", run_id)
        for _ in range(4):                       # the runs module writes its record on the same event
            if rec:
                break
            await asyncio.sleep(0.15)
            rec = await self.core.db.repo.get("run", run_id)
        if not rec:
            raise dbconn.DbError(f"run record '{run_id}' not found — cannot build the MES result")
        data = rec["data"]
        started = data.get("started_ts")
        finished = data.get("finished_ts") or event_ts or time.time()
        stamp = await self._business_stamp(started or finished)
        model = await self._recipe_model(data.get("recipe_id")) or data.get("model")
        return {
            "run_id": run_id, "stage": self.stage, "station": self.core.station,
            "serial_no": data.get("serial_no") or "",
            "model": model, "operator": data.get("operator"),
            "recipe_id": data.get("recipe_id"), "recipe_version": data.get("recipe_version"),
            "result": body.get("result") or data.get("result") or "UNKNOWN",
            "started_ts": started, "finished_ts": finished, "created_at": finished,
            "business_day": stamp["business_day"], "shift_label": stamp["shift_label"],
        }

    async def _business_stamp(self, ts) -> dict:
        from datetime import datetime
        if not ts:
            return {"business_day": None, "shift_label": None}
        get = getattr(self.core, "get_contract", None)
        if get is not None:
            try:
                info = await get("config").shift_for(ts)
                return {"business_day": info["business_day"], "shift_label": info.get("shift_label")}
            except Exception:  # noqa: BLE001 — no config module → plain calendar day
                pass
        return {"business_day": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), "shift_label": None}

    async def _recipe_model(self, recipe_id) -> str | None:
        get = getattr(self.core, "get_contract", None)
        if not recipe_id or get is None:
            return None
        try:
            return (await get("recipe").get_recipe(recipe_id)).get("model") or None
        except Exception:  # noqa: BLE001 — no recipe module / no model → keep the run-record model
            return None

    # --- failures: loud, persisted as status only (NO outbox, NO payload copy) ------------------

    async def _record_failure(self, run_id: str, serial: str, result, exc: Exception) -> None:
        msg = dbconn.short_error(exc) if not isinstance(exc, dbconn.DbError) else str(exc)
        if isinstance(exc, asyncio.TimeoutError):
            msg = "MES database timed out"
        await self.core.db.repo.put(
            _PUSH, {"run_id": run_id, "serial": serial, "result": result, "status": "failed",
                    "error": msg, "ts": time.time()},
            id=run_id, summary=f"MES push failed {serial or run_id}")
        self.core.diag.error("mes", "outbound push failed", run_id=run_id, serial=serial, error=msg)

    async def _failed(self) -> list[dict]:
        rows = await self.core.db.repo.query(_PUSH, filter={"status": "failed"})
        return [r["data"] for r in rows]

    async def alerts(self) -> list[dict]:
        return sorted(await self._failed(), key=lambda a: a.get("ts", 0), reverse=True)

    async def alert_retry(self, run_id: str) -> dict:
        rec = await self.core.db.repo.get(_PUSH, run_id)
        if not rec:
            return {"ok": True, "detail": "nothing to retry"}
        fail = rec["data"]
        try:
            row = await self._build_row(run_id, {"result": fail.get("result")}, None)
            if not row["serial_no"]:
                raise dbconn.DbError("run has no serial number")
            await self.provider.publish_result(row["serial_no"], row["result"], row)
        except Exception as exc:  # noqa: BLE001 — stay loud
            await self._record_failure(run_id, fail.get("serial", ""), fail.get("result"), exc)
            return {"ok": False, "detail": (await self.core.db.repo.get(_PUSH, run_id))["data"]["error"]}
        await self.core.db.repo.delete_id(_PUSH, run_id)
        self.core.diag.info("mes", "outbound push retried ok", run_id=run_id, serial=row["serial_no"])
        return {"ok": True, "detail": "delivered"}

    async def alert_dismiss(self, run_id: str, by: str = "") -> dict:
        rec = await self.core.db.repo.get(_PUSH, run_id)
        if rec:
            await self.core.db.repo.delete_id(_PUSH, run_id)
            self.core.diag.warning("mes", "outbound failure dismissed WITHOUT delivery", run_id=run_id,
                                   serial=rec["data"].get("serial"), by=by,
                                   error=rec["data"].get("error"))
        return {"ok": True}

    # --- runtime config (Config → MES) --------------------------------------------------------

    async def status(self) -> dict:
        return {
            "stage": self.stage, "provider": self.provider_kind,
            "gate_enabled": self.gate_enabled, "publish_enabled": self.publish_enabled,
            "on_missing": self.on_missing, "on_error": self.on_error,
            "provider_detail": self.provider.describe(),
            "failed_pushes": len(await self._failed()),
        }

    async def set_config(self, gate_enabled=None, publish_enabled=None, provider=None,
                         on_missing=None, on_error=None) -> dict:
        if provider is not None and provider not in _PROVIDERS:
            raise ValueError(f"provider must be one of {', '.join(_PROVIDERS)}")
        for name, v in (("on_missing", on_missing), ("on_error", on_error)):
            if v is not None and v not in _POLICY:
                raise ValueError(f"{name} must be 'block' or 'allow'")
        rebuild = False
        if gate_enabled is not None:
            self.gate_enabled = bool(gate_enabled)
        if publish_enabled is not None:
            self.publish_enabled = bool(publish_enabled)
        if provider is not None and provider != self.provider_kind:
            self.provider_kind, rebuild = provider, True
        if on_missing is not None and on_missing != self.on_missing:
            self.on_missing, rebuild = on_missing, True
        if on_error is not None and on_error != self.on_error:
            self.on_error, rebuild = on_error, True
        if rebuild:
            self._rebuild_provider()
        await self.core.db.repo.put(
            "mes_setting",
            {"gate_enabled": self.gate_enabled, "publish_enabled": self.publish_enabled,
             "provider": self.provider_kind, "on_missing": self.on_missing, "on_error": self.on_error},
            id=_SETTING_ID, summary="mes settings",
        )
        self.core.diag.info("mes", "settings updated", gate=self.gate_enabled,
                            publish=self.publish_enabled, provider=self.provider_kind)
        return await self.status()

    # --- database settings ---------------------------------------------------------------------

    def get_db_config(self) -> dict:
        return {**_redact(self.db_config), "fields": S.catalog()}

    async def set_db_config(self, body: dict) -> dict:
        new = copy.deepcopy(self.db_config)
        for side in ("inbound", "outbound"):
            if side in body and isinstance(body[side], dict):
                new[side] = _merge_side(new.get(side) or {}, body[side])
        self.db_config = new
        await self.core.db.repo.put("mes_db_config", new, id=_DB_ID, summary="mes database settings")
        self._rebuild_provider()
        self.core.diag.info("mes", "database settings updated")
        return self.get_db_config()

    # --- the configuration "process": discovery helpers (stateless; draft from the UI) ----------

    def _conn(self, side: str, draft: dict | None, *, same_as_inbound: bool = False) -> dict:
        """Connection to use: the UI's draft, with the STORED password when the draft leaves it blank
        and points at the same server (so the password never has to round-trip through the browser).
        `same_as_inbound` (outbound only) = the stored inbound connection."""
        inbound = (self.db_config.get("inbound") or {}).get("connection") or {}
        if side == "outbound" and same_as_inbound:
            return dict(inbound)
        stored = (self.db_config.get(side) or {}).get("connection") or {}
        d = {k: v for k, v in (draft or {}).items() if k in CONN_KEYS}
        if not d:
            return dict(stored)
        if not d.get("password") and _same_server(stored, d):
            d["password"] = stored.get("password", "")
        return d

    async def _io(self, fn, *a, **kw):
        return await asyncio.get_running_loop().run_in_executor(None, lambda: fn(*a, **kw))

    async def _listing(self, fn, *a) -> dict:
        """Run a listing; NEVER fail the request — the UI falls back to typing the name by hand."""
        try:
            return {"ok": True, "items": await self._io(fn, *a), "detail": ""}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "items": [], "detail": dbconn.short_error(exc)}

    async def db_test(self, side: str, conn: dict | None, same_as_inbound: bool = False) -> dict:
        cfg = self._conn(side, conn, same_as_inbound=same_as_inbound)
        return await self._io(dbconn.connect_check, cfg)

    async def db_databases(self, side: str, conn: dict | None, same_as_inbound: bool = False) -> dict:
        return await self._listing(dbconn.list_databases, self._conn(side, conn, same_as_inbound=same_as_inbound))

    async def db_tables(self, side: str, conn: dict | None, database: str | None,
                        same_as_inbound: bool = False) -> dict:
        return await self._listing(dbconn.list_tables,
                                   self._conn(side, conn, same_as_inbound=same_as_inbound), database)

    async def db_columns(self, side: str, conn: dict | None, database: str | None, table: str,
                         same_as_inbound: bool = False) -> dict:
        return await self._listing(dbconn.list_columns,
                                   self._conn(side, conn, same_as_inbound=same_as_inbound), database, table)

    async def db_values(self, conn: dict | None, database: str | None, table: str, column: str) -> dict:
        return await self._listing(dbconn.distinct_values, self._conn("inbound", conn), database, table, column)

    async def db_verify(self, side: str, conn: dict | None, database: str | None, table: str,
                        columns: list[str], same_as_inbound: bool = False) -> dict:
        """Confirm manually typed names: SELECT <columns> FROM <table> (1 row)."""
        cols = [c for c in columns if c]
        if not table or not cols:
            return {"ok": False, "detail": "enter a table and at least one column"}
        try:
            await self._io(dbconn.probe, self._conn(side, conn, same_as_inbound=same_as_inbound),
                           database, table, cols)
            return {"ok": True, "detail": "table and columns found"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": dbconn.short_error(exc)}

    async def inbound_check(self, serial: str, draft: dict | None = None) -> dict:
        """Dry run of the gate for `serial` using the DRAFT inbound settings (or the stored ones).
        No side effects. -> {allowed, prior_result, detail, rows}"""
        cfg = copy.deepcopy(draft) if draft else copy.deepcopy(self.db_config.get("inbound") or {})
        cfg["connection"] = self._conn("inbound", cfg.get("connection"))
        probe = DbInbound(cfg, on_missing=self.on_missing, on_error="block")
        try:
            rows = []
            if not probe.problem():
                try:
                    rows = [str(v) for v in await probe.lookup(serial)]
                except Exception:  # noqa: BLE001 — check() below reports it
                    rows = []
            res = await probe.check(serial)
            return {"allowed": res.allowed, "prior_result": res.prior_result, "detail": res.detail,
                    "rows": rows[:20], "matched": len(rows)}
        finally:
            probe.dispose()

    def _outbound(self, draft: dict | None) -> DbOutbound:
        cfg = copy.deepcopy(draft) if draft else copy.deepcopy(self.db_config.get("outbound") or {})
        cfg["connection"] = self._conn("outbound", cfg.get("connection"),
                                       same_as_inbound=bool(cfg.get("same_as_inbound")))
        return DbOutbound(cfg)

    async def outbound_validate(self, draft: dict | None = None) -> dict:
        ob = self._outbound(draft)
        try:
            return await self._io(ob.validate)
        finally:
            ob.dispose()

    async def outbound_ensure(self, draft: dict | None = None, add_missing: bool = False) -> dict:
        ob = self._outbound(draft)
        try:
            out = await self._io(ob.ensure, add_missing=add_missing)
        except dbconn.DbError as exc:
            return {"ok": False, "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": dbconn.short_error(exc)}
        finally:
            ob.dispose()
        self.core.diag.info("mes", "outbound table ensured", table=(draft or {}).get("table"),
                            add_missing=add_missing, ok=out.get("ok"))
        return out

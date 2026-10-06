"""Report `standard` variant — assemble on run-finished, spool to a local outbox,
forward to the professional DB (ReportStore), and query the DB for reports/analytics.

Reports are business-critical: the pro DB (MySQL / SQL Server) is the system of record;
a local SQLite outbox guarantees run-finish never blocks on or loses a report. Optional
folder sinks still mirror to CSV/JSON.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.config import migrate_cwd_state, resolve_state_path
from modules.report.api import build_router
from modules.report.assembly import build_report, result_is_pass
from modules.report.outbox import Outbox
from modules.report.sinks import build_sinks, when_matches
from modules.report.sinks.folder import report_to_csv
from modules.report.store import ReportStore, StoreError

_DB_CFG_ID = "report_db"
_RETRY_S = 30.0


class StandardReport:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.station = core.station
        self._sinks = build_sinks(config, core.db)          # optional folder mirrors only
        self.store = ReportStore(core.diag)
        # The outbox holds finished reports until the pro DB accepts them — resolve it under the
        # EXTERNAL deploy root, never the CWD (=run.dist when frozen), or an update swap orphans
        # any reports not yet forwarded (UPDATES.md §4.1).
        _outbox_cfg = config.get("outbox_path") or "data/report_outbox.sqlite"
        if _outbox_cfg == ":memory:" or Path(_outbox_cfg).is_absolute():
            outbox_path = str(_outbox_cfg)
        else:
            _resolved = resolve_state_path(_outbox_cfg)
            migrate_cwd_state(_outbox_cfg, _resolved, core.diag)
            outbox_path = str(_resolved)
        self.outbox = Outbox(outbox_path)
        self._kick = asyncio.Event()
        self._forwarder: asyncio.Task | None = None
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "StandardReport":
        return cls(core, config)

    async def init(self) -> None:
        cfg = await self.get_db_config(redacted=False)
        if cfg.get("provider"):
            self.store.configure(cfg)

    async def start(self) -> None:
        await self.outbox.connect()
        if self.store.configured:
            try:
                await self.store.ensure_schema()
            except Exception as exc:  # noqa: BLE001 — DB down at boot must not block start
                self.core.diag.warning("report", "report DB schema check failed at boot", error=str(exc))
        self._forwarder = asyncio.create_task(self._forward_loop())

    async def stop(self) -> None:
        if self._forwarder:
            self._forwarder.cancel()
            try:
                await self._forwarder
            except asyncio.CancelledError:
                pass
        await self.outbox.close()
        self.store.dispose()

    async def health(self) -> Health:
        pending = await self.outbox.count()
        if not self.store.configured:
            return Health(status=HealthStatus.DEGRADED, detail="report DB not configured")
        detail = f"store configured · outbox pending {pending}"
        return Health(status=HealthStatus.DEGRADED if pending else HealthStatus.OK, detail=detail)

    # --- assembly + spool --------------------------------------------------

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        if etype != "run-finished":
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id")
        if not run_id:
            return
        events = [r["data"] for r in await self.core.db.repo.query("run_event", filter={"run_id": run_id})]
        rec = await self.core.db.repo.get("run", run_id)
        run_record = rec["data"] if rec else None
        report = build_report(run_id, events, {**body, "ts": payload.get("ts")}, self.station, run_record)
        start_ts = (run_record or {}).get("started_ts") or report.get("ts") or payload.get("ts")
        stamp = await self._business_stamp(start_ts)
        report["business_day"] = stamp["business_day"]
        report["shift_label"] = stamp["shift_label"]
        model = await self._recipe_model(report.get("recipe_id"))   # Model is a recipe field
        if model:
            report["model"] = model

        await self.outbox.enqueue(report)                   # write-ahead: never lost
        self._kick.set()
        is_pass = result_is_pass(report["result"])
        for sink in self._sinks:                            # optional CSV/JSON mirrors
            if when_matches(sink.when, is_pass):
                await sink.write(report)
        self.core.diag.info("report", "report spooled", run_id=run_id, result=report["result"])

    async def _business_stamp(self, ts) -> dict:
        from datetime import datetime
        if not ts:
            return {"business_day": None, "shift_label": None}
        get = getattr(self.core, "get_contract", None)
        if get is not None:
            try:
                info = await get("config").shift_for(ts)
                return {"business_day": info["business_day"], "shift_label": info.get("shift_label")}
            except KeyError:
                pass
        return {"business_day": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), "shift_label": None}

    async def _recipe_model(self, recipe_id) -> str | None:
        if not recipe_id:
            return None
        get = getattr(self.core, "get_contract", None)
        if get is None:
            return None
        try:
            r = await get("recipe").get_recipe(recipe_id)
            return r.get("model") or None
        except Exception:  # noqa: BLE001 — no recipe / no model -> keep the run-record model
            return None

    # --- forwarder ---------------------------------------------------------

    async def _forward_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), timeout=_RETRY_S)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            self._kick.clear()
            await self._drain()

    async def _drain(self) -> int:
        """Forward queued reports to the pro DB; keep + retry on failure. Returns the
        number forwarded (also called directly by tests)."""
        if not self.store.configured:
            return 0
        sent = 0
        for item in await self.outbox.pending():
            try:
                await self.store.write(item["report"])
                await self.outbox.mark_done(item["run_id"])
                sent += 1
            except Exception as exc:  # noqa: BLE001 — keep the report; retry later
                await self.outbox.mark_failed(item["run_id"], str(exc))
                self.core.diag.warning("report", "forward to report DB failed (queued)",
                                       run_id=item["run_id"], error=str(exc).splitlines()[0][:200])
                break                                       # DB likely down; stop, retry next tick
        return sent

    # --- DB config ---------------------------------------------------------

    async def get_db_config(self, *, redacted: bool = True) -> dict:
        rec = await self.core.db.repo.get("config", _DB_CFG_ID)
        cfg = (rec["data"] if rec else {}) or {}
        if not redacted:
            return cfg
        return {"provider": cfg.get("provider"), "host": cfg.get("host"), "port": cfg.get("port"),
                "database": cfg.get("database"), "user": cfg.get("user"),
                "odbc_driver": cfg.get("odbc_driver"), "has_password": bool(cfg.get("password")),
                "configured": bool(cfg.get("provider"))}

    _NON_CFG = {"has_password", "configured"}     # redacted GET fields; never stored

    def _merge(self, body: dict, current: dict) -> dict:
        cfg = {**current, **{k: v for k, v in (body or {}).items()
                             if k != "password" and k not in self._NON_CFG}}
        pw = (body or {}).get("password")
        cfg["password"] = pw if pw else current.get("password")   # blank keeps the stored password
        return cfg

    async def set_db_config(self, body: dict) -> dict:
        current = await self.get_db_config(redacted=False)
        cfg = self._merge(body, current)
        await self.core.db.repo.put("config", cfg, id=_DB_CFG_ID, summary=f"report DB: {cfg.get('provider')}")
        self.store.configure(cfg if cfg.get("provider") else None)
        if self.store.configured:
            try:
                await self.store.ensure_schema()
            except Exception as exc:  # noqa: BLE001
                self.core.diag.warning("report", "schema check failed after config", error=str(exc))
        self._kick.set()
        self.core.diag.info("report", "report DB configured", provider=cfg.get("provider"))
        return await self.get_db_config()

    async def test_db_config(self, body: dict) -> dict:
        current = await self.get_db_config(redacted=False)
        return await self.store.test_connection(self._merge(body or {}, current))

    # --- queries (delegated to the professional DB) ------------------------

    async def get_report(self, run_id: str) -> dict | None:
        return await self.store.get_report(run_id)

    async def list_reports(self, **f) -> dict:
        return await self.store.list_reports(**f)

    async def report_models(self) -> list[str]:
        return await self.store.report_models()

    async def full_matrix(self, **f) -> dict:
        return await self.store.full_matrix(**f)

    async def full_csv(self, **f) -> bytes:
        return await self.store.full_csv(**f)

    async def full_export(self, fmt: str, spec, *, limit: int = 20000, **f) -> dict:
        """Bulk export of the filtered matrix in a registered format (xlsx / tdms / …).
        Returns {data, filename_ext, media_type, rows, total, truncated}."""
        from datetime import datetime

        from modules.report.exporters import ExportError, get_format
        fmt_obj = get_format(fmt)
        matrix = await self.store.full_matrix(limit=limit, **f)
        if not matrix.get("configured", True):
            raise ExportError("The report database is not configured — nothing to export. "
                              "Set it in Settings → Report database.", status=409)
        meta = {"station": self.station, "filters": f,
                "exported_at": datetime.now().isoformat(timespec="seconds")}
        data = await asyncio.get_running_loop().run_in_executor(
            None, lambda: fmt_obj.build(matrix, spec, meta))     # CPU-bound; keep the loop free
        return {"data": data, "ext": fmt_obj.ext, "media_type": fmt_obj.media_type,
                "rows": len(matrix["rows"]), "total": matrix["total"], "truncated": matrix["truncated"]}

    async def dashboard(self, since=None, until=None, model=None, operator=None, shift=None, station=None) -> dict:
        return await self.store.dashboard(since=since, until=until, model=model, operator=operator,
                                          shift=shift, station=station)

    async def analytics(self, since=None, until=None, recipe_id=None) -> dict:
        d = await self.store.dashboard(since=since, until=until)
        k = d.get("kpis", {})
        return {"total": k.get("runs", 0), "passed": k.get("passed", 0), "failed": k.get("failed", 0),
                "yield": k.get("yield", 0.0), "configured": d.get("configured", False)}

    async def export(self, run_id: str, fmt: str = "json") -> bytes:
        report = await self.get_report(run_id)
        if report is None:
            raise KeyError(run_id)
        if fmt == "csv":
            return report_to_csv(report).encode("utf-8")
        return json.dumps(report, indent=2, default=str).encode("utf-8")

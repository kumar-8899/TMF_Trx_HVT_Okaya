"""`okaya_mes` default variant — writes ONE wide row per finished run into Okaya's legacy MES table.

This is the app-owned counterpart of the framework `mes` module's database outbound: that one writes a
header-only row; Okaya's table (shared with three older benches) holds per-test min / max / actual / result,
so the row is built here (`rowbuilder`) from the run record and written with `writer`. The framework `mes`
module's publish stays OFF for this bench — this module is the only thing that writes the table.

Like the framework MES it is INSTANT and LOUD: the row is sent the moment `run-finished` arrives. A failure is
never queued or retried silently — an `okaya_mes_push` status record keeps it (and a diag error, and a DEGRADED
health) until the operator presses Retry (the row is rebuilt from the run record) or Dismiss.

Settings (enabled, connection, database, table, station name) live in a record edited on the
**MES (Okaya table)** page; `app.json` only supplies defaults.
"""

from __future__ import annotations

import asyncio
import copy
import time

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services import dbconn
from modules.okaya_mes import rowbuilder as rb
from modules.okaya_mes import writer
from modules.okaya_mes.api import build_router

_SETTING_TYPE, _SETTING_ID = "okaya_mes_setting", "okaya_mes"
_PUSH = "okaya_mes_push"
CONN_KEYS = ("provider", "host", "port", "user", "password", "odbc_driver", "path")


def _same_server(a: dict, b: dict) -> bool:
    """A stored password is only ever re-used for the SAME server (never sent to a different host)."""
    return all(str(a.get(k) or "") == str(b.get(k) or "") for k in ("provider", "host", "port", "user", "path"))


def _redact(cfg: dict) -> dict:
    out = copy.deepcopy(cfg)
    conn = out.get("connection")
    if isinstance(conn, dict):
        conn["has_password"] = bool(conn.pop("password", None))
    return out


class OkayaMes:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config or {}
        self.station_name: str = self.config.get("station_name") or rb.DEFAULT_STATION_NAME
        self.enabled = bool(self.config.get("enabled", False))
        self.database: str = self.config.get("database") or ""
        self.table: str = self.config.get("table") or ""
        self.connection: dict = copy.deepcopy(self.config.get("connection") or {})
        self.timeout = float(self.config.get("timeout_s", 10.0))
        self.complete_timeout_s = float(self.config.get("complete_timeout_s", 5.0))   # wait for the run record to be complete
        self._engine = None
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> OkayaMes:
        return cls(core, config)

    # --- lifecycle ---------------------------------------------------------------------------

    async def init(self) -> None:
        rec = await self.core.db.repo.get(_SETTING_TYPE, _SETTING_ID)
        if rec:
            d = rec["data"]
            self.enabled = bool(d.get("enabled", self.enabled))
            self.station_name = d.get("station_name") or self.station_name
            self.database = d.get("database", self.database) or ""
            self.table = d.get("table", self.table) or ""
            self.connection = d.get("connection") or self.connection

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        self._dispose()

    def _dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None

    def _eng(self):
        if self._engine is None:
            self._engine = dbconn.make_engine(self.connection, self.database or None,
                                              connect_timeout=min(self.timeout, 8))
        return self._engine

    def problem(self) -> str | None:
        if not (self.connection or {}).get("provider"):
            return "no database server configured"
        if self.connection.get("provider") != "sqlite" and not self.database:
            return "database not chosen"
        if not self.table:
            return "table not chosen"
        return None

    async def health(self) -> Health:
        failed = len(await self._failed())
        detail = f"okaya table · enabled={self.enabled}"
        if failed:
            return Health(status=HealthStatus.DEGRADED,
                          detail=f"{failed} MES result(s) NOT delivered to the Okaya table — needs attention · {detail}")
        if self.enabled and self.problem():
            return Health(status=HealthStatus.DEGRADED, detail=f"enabled but not configured ({self.problem()})")
        return Health(status=HealthStatus.OK, detail=detail)

    # --- run-finished -> one row --------------------------------------------------------------

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload or not self.enabled:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        if etype != "run-finished":
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id")
        if not run_id:
            return
        serial = ""
        try:
            run = await self._run_record(run_id, body, payload.get("ts"))
            serial = run.get("serial_no") or ""
            if not serial:
                self.core.diag.warning("okaya_mes", "run has no serial number — nothing written to the Okaya table",
                                       run_id=run_id)
                return
            await self._push(run)
            await self.core.db.repo.delete_id(_PUSH, run_id)            # a stale failure for this run is moot
        except Exception as exc:  # noqa: BLE001 — never lose a delivery failure
            await self._record_failure(run_id, serial, body.get("result"), exc)

    async def _run_record(self, run_id: str, body: dict | None = None, event_ts=None, *, wait: bool = True) -> dict:
        """The run record's data, once it is COMPLETE.

        The runs module stores every `test-result` and then `run-finished` one event at a time, and this handler is
        triggered by the very same `run-finished` — so reading the record straight away can miss the LAST test(s)
        (seen live: a 3-test run whose third test was NULL in the table). A row is only built from a record that is
        (a) marked `finished` and (b) holds as many results as there were `test-result` events for the run. If that
        does not happen within `complete_timeout_s` the write FAILS LOUDLY (Retry later rebuilds it) — it never
        writes a partial row. `wait=False` (preview) takes the record as it is."""
        repo = self.core.db.repo
        deadline = time.monotonic() + (self.complete_timeout_s if wait else 0.0)
        while True:
            rec = await repo.get("run", run_id)
            expected = len(await repo.query("run_event", filter={"run_id": run_id, "type": "test-result"}))
            stored = len((rec["data"].get("results") or []) if rec else [])
            done = bool(rec) and rec["data"].get("status") == "finished" and stored >= expected
            if done or time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.1)
        if not rec:
            raise dbconn.DbError(f"run record '{run_id}' not found — cannot build the MES result")
        if wait and not done:
            raise dbconn.DbError(
                f"run '{run_id}' is not complete in the run record after {self.complete_timeout_s:g} s "
                f"(status {rec['data'].get('status')!r}, {stored} of {expected} test results stored) — nothing written; "
                "press Retry once it has finished")
        run = dict(rec["data"])
        run.setdefault("run_id", run_id)
        if not run.get("finished_ts"):
            run["finished_ts"] = event_ts or time.time()
        if not run.get("result") and body:
            run["result"] = body.get("result")
        return run

    def build_row(self, run: dict) -> dict:
        return rb.build_row(run, station_name=self.station_name)

    async def _push(self, run: dict) -> dict:
        problem = self.problem()
        if problem:
            raise dbconn.DbError(f"Okaya MES database is not configured ({problem})")
        row = self.build_row(run)
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, writer.write_row, self._eng(), self.table, row), self.timeout)
        except asyncio.TimeoutError as exc:
            self._dispose()
            raise dbconn.DbError(f"Okaya MES database did not answer within {self.timeout:g} s") from exc
        except Exception:
            self._dispose()                      # drop a possibly dead pooled connection
            raise
        self.core.diag.info("okaya_mes", "result written to the Okaya table", run_id=run.get("run_id"),
                            serial=row["serial_no"], result=row["result"], failed_test=row["failed_test"])
        return row

    # --- failures: loud, persisted as status only ----------------------------------------------

    async def _record_failure(self, run_id: str, serial: str, result, exc: Exception) -> None:
        msg = str(exc) if isinstance(exc, dbconn.DbError) else dbconn.short_error(exc)
        if isinstance(exc, asyncio.TimeoutError):
            msg = "Okaya MES database timed out"
        await self.core.db.repo.put(
            _PUSH, {"run_id": run_id, "serial": serial, "result": result, "status": "failed",
                    "error": msg, "ts": time.time()},
            id=run_id, summary=f"Okaya MES push failed {serial or run_id}")
        self.core.diag.error("okaya_mes", "write to the Okaya table failed", run_id=run_id, serial=serial, error=msg)

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
            run = await self._run_record(run_id)
            if not run.get("serial_no"):
                raise dbconn.DbError("run has no serial number")
            row = await self._push(run)
        except Exception as exc:  # noqa: BLE001 — stay loud
            await self._record_failure(run_id, fail.get("serial", ""), fail.get("result"), exc)
            return {"ok": False, "detail": (await self.core.db.repo.get(_PUSH, run_id))["data"]["error"]}
        await self.core.db.repo.delete_id(_PUSH, run_id)
        return {"ok": True, "detail": f"delivered ({row['serial_no']})"}

    async def alert_dismiss(self, run_id: str, by: str = "") -> dict:
        rec = await self.core.db.repo.get(_PUSH, run_id)
        if rec:
            await self.core.db.repo.delete_id(_PUSH, run_id)
            self.core.diag.warning("okaya_mes", "write failure dismissed WITHOUT delivery", run_id=run_id,
                                   serial=rec["data"].get("serial"), by=by, error=rec["data"].get("error"))
        return {"ok": True}

    async def preview(self, run_id: str) -> dict:
        """The exact row that WOULD be written for a run (no database involved) — to check it against the
        customer's template before pointing this at the live table."""
        run = await self._run_record(run_id, wait=False)
        row = self.build_row(run)
        return {"run_id": run_id, "columns": list(rb.COLUMNS),
                "row": {k: (v.isoformat(sep=" ") if hasattr(v, "isoformat") else v) for k, v in row.items()}}

    async def send_run(self, run_id: str) -> dict:
        """Write one finished run's row now (admin action): backfill a run made before this module was
        switched on, or re-send one. Same path as the live push; works even while `enabled` is off."""
        run = await self._run_record(run_id)
        if not run.get("serial_no"):
            raise dbconn.DbError("run has no serial number")
        row = await self._push(run)
        await self.core.db.repo.delete_id(_PUSH, run_id)
        return {"ok": True, "serial_no": row["serial_no"], "result": row["result"],
                "failed_test": row["failed_test"]}

    # --- settings ------------------------------------------------------------------------------

    async def status(self) -> dict:
        return {"enabled": self.enabled, "station_name": self.station_name, "database": self.database,
                "table": self.table, "ready": self.problem() is None, "problem": self.problem(),
                "failed_pushes": len(await self._failed())}

    def get_config(self) -> dict:
        return _redact({"enabled": self.enabled, "station_name": self.station_name, "database": self.database,
                        "table": self.table, "connection": self.connection})

    async def set_config(self, body: dict) -> dict:
        if "enabled" in body:
            self.enabled = bool(body["enabled"])
        if "station_name" in body:
            self.station_name = (str(body["station_name"]).strip()[:rb.TEXT_LEN]) or rb.DEFAULT_STATION_NAME
        if "database" in body:
            self.database = str(body["database"] or "").strip()
        if "table" in body:
            self.table = str(body["table"] or "").strip()
        if "connection" in body and isinstance(body["connection"], dict):
            self.connection = self._merge_conn(body["connection"])
        self._dispose()
        await self.core.db.repo.put(
            _SETTING_TYPE, {"enabled": self.enabled, "station_name": self.station_name, "database": self.database,
                            "table": self.table, "connection": self.connection},
            id=_SETTING_ID, summary="okaya mes settings")
        self.core.diag.info("okaya_mes", "settings updated", enabled=self.enabled, table=self.table,
                            database=self.database)
        return self.get_config()

    def _merge_conn(self, draft: dict) -> dict:
        """The UI's draft connection; a blank password keeps the stored one (same server only), so the
        password never has to round-trip through the browser."""
        d = {k: v for k, v in (draft or {}).items() if k in CONN_KEYS}
        if not d.get("password"):
            d.pop("password", None)
            if self.connection.get("password") and _same_server(self.connection, d):
                d["password"] = self.connection["password"]
        return d

    # --- discovery / checks (stateless: fed with the UI's draft) --------------------------------

    async def _io(self, fn, *a, **kw):
        return await asyncio.get_running_loop().run_in_executor(None, lambda: fn(*a, **kw))

    async def _listing(self, fn, *a) -> dict:
        try:
            return {"ok": True, "items": await self._io(fn, *a), "detail": ""}
        except Exception as exc:  # noqa: BLE001 — never fail the request; the UI falls back to typing
            return {"ok": False, "items": [], "detail": dbconn.short_error(exc)}

    async def db_test(self, draft: dict | None) -> dict:
        return await self._io(dbconn.connect_check, self._merge_conn(draft or {}) if draft else self.connection)

    async def db_databases(self, draft: dict | None) -> dict:
        return await self._listing(dbconn.list_databases, self._merge_conn(draft or {}) if draft else self.connection)

    async def db_tables(self, draft: dict | None, database: str | None) -> dict:
        return await self._listing(dbconn.list_tables, self._merge_conn(draft or {}) if draft else self.connection,
                                   database or self.database)

    async def check_table(self, draft: dict | None, database: str | None, table: str | None) -> dict:
        conn = self._merge_conn(draft or {}) if draft else self.connection
        return await self._io(writer.validate, conn, database or self.database or None, table or self.table)

    async def create_table(self, draft: dict | None, database: str | None, table: str | None) -> dict:
        conn = self._merge_conn(draft or {}) if draft else self.connection
        try:
            return await self._io(writer.ensure, conn, database or self.database or None, table or self.table)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": dbconn.short_error(exc), "exists": False, "missing": [],
                    "wrong_type": [], "blocking": [], "columns": []}

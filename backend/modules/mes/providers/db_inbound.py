"""MES inbound (gate) against a customer database — READ-ONLY.

"May this serial be tested here?" = look the DUT up in a customer table and compare a status column
with the configured *allow* value. Equal → allowed; **anything else → blocked**. The query is built with
SQLAlchemy Core `table()/column()` (parameterised, quoted per dialect, no reflection) so it also works
with names typed by hand when auto-listing isn't permitted. Nothing is ever written or created here.

Config (`inbound`):
    connection       {provider, host, port, user, password, odbc_driver, path}
    database, table  where the status lives (table may be a view; 'schema.table' for non-default schemas)
    serial_column    column holding the DUT serial / barcode
    status_column    column holding the previous-stage result
    allow_value      the value that means "allowed" (everything else blocks)
    ignore_case      compare trimmed text case-insensitively (default true)
    latest_by        ordered list of 1..n columns, newest first (e.g. [date_col, time_col] when a
                     history table keeps date and time in separate columns); empty = no ordering
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from core.services import dbconn
from core.services.interlock import InterlockResult


def _norm(v, ignore_case: bool) -> str:
    s = str(v).strip()
    return s.lower() if ignore_case else s


def decide(statuses: list, allow_value: str, *, ignore_case: bool, ordered: bool,
           on_missing: str) -> InterlockResult:
    """Pure decision. `statuses` are the status values of the matching rows, newest first when `ordered`."""
    if not statuses:
        if on_missing == "allow":
            return InterlockResult(allowed=True, detail="no MES record for this serial (allowed by policy)")
        return InterlockResult(allowed=False, detail="no MES record for this serial")
    want = _norm(allow_value, ignore_case)
    if ordered:       # newest row wins
        got = statuses[0]
        ok = _norm(got, ignore_case) == want
        return InterlockResult(allowed=ok, prior_result=str(got).strip(),
                               detail="MES status allowed" if ok else
                               f"MES status is '{str(got).strip()}', not '{allow_value}'")
    # no ordering column: every matching row must allow (fail-safe for history tables)
    bad = [s for s in statuses if _norm(s, ignore_case) != want]
    if not bad:
        return InterlockResult(allowed=True, prior_result=str(statuses[0]).strip(),
                               detail="MES status allowed")
    extra = f" ({len(statuses)} rows matched; set 'Latest by' to use only the newest)" if len(statuses) > 1 else ""
    return InterlockResult(allowed=False, prior_result=str(bad[0]).strip(),
                           detail=f"MES status is '{str(bad[0]).strip()}', not '{allow_value}'{extra}")


class DbInbound:
    def __init__(self, cfg: dict, *, on_missing: str = "block", on_error: str = "block",
                 timeout: float = 6.0) -> None:
        self.cfg = cfg or {}
        self.on_missing, self.on_error, self.timeout = on_missing, on_error, timeout
        self._engine = None

    # --- config ----------------------------------------------------------------------------

    @property
    def latest_by(self) -> list[str]:
        return [c for c in (self.cfg.get("latest_by") or []) if c]

    def problem(self) -> str | None:
        """Why this inbound can't run yet (None = ready)."""
        c = self.cfg
        if not (c.get("connection") or {}).get("provider"):
            return "no database server configured"
        for key, label in (("table", "table"), ("serial_column", "serial column"),
                           ("status_column", "status column")):
            if not c.get(key):
                return f"{label} not chosen"
        if str(c.get("allow_value", "")) == "":
            return "allow value not set"
        if c.get("connection", {}).get("provider") != "sqlite" and not c.get("database"):
            return "database not chosen"
        return None

    def describe(self) -> dict:
        c = self.cfg
        return {"database": c.get("database"), "table": c.get("table"),
                "serial_column": c.get("serial_column"), "status_column": c.get("status_column"),
                "allow_value": c.get("allow_value"), "latest_by": self.latest_by,
                "ready": self.problem() is None, "problem": self.problem()}

    # --- query -----------------------------------------------------------------------------

    def _eng(self):
        if self._engine is None:
            self._engine = dbconn.make_engine(self.cfg["connection"], self.cfg.get("database"),
                                              connect_timeout=self.timeout)
        return self._engine

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _statuses(self, serial: str) -> list:
        c = self.cfg
        t = dbconn.lw_table(c["table"], [c["serial_column"], c["status_column"], *self.latest_by])
        q = select(t.c[c["status_column"]]).where(t.c[c["serial_column"]] == serial)
        if self.latest_by:
            q = q.order_by(*dbconn.order_desc(t, self.latest_by)).limit(1)
        else:
            q = q.limit(1000)
        with self._eng().connect() as conn:
            return [r[0] for r in conn.execute(q).all()]

    async def lookup(self, serial: str) -> list:
        """Raw status values for `serial` (raises on DB errors). Used by check() and the dry-run."""
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(loop.run_in_executor(None, self._statuses, serial), self.timeout + 2)

    async def check(self, serial: str) -> InterlockResult:
        """Never raises: any failure resolves through the `on_error` policy (default block)."""
        problem = self.problem()
        try:
            if problem:
                raise dbconn.DbError(f"MES inbound database is not configured ({problem})")
            statuses = await self.lookup(serial)
        except Exception as exc:  # noqa: BLE001 — a gate must answer, loudly
            msg = (str(exc) if isinstance(exc, dbconn.DbError) else
                   "MES database timed out" if isinstance(exc, asyncio.TimeoutError) else
                   f"MES database error: {dbconn.short_error(exc)}")
            self.dispose()                      # next call reconnects instead of reusing a dead engine
            return InterlockResult(allowed=self.on_error == "allow",
                                   detail=msg + (" (allowed by policy)" if self.on_error == "allow" else ""))
        return decide(statuses, self.cfg.get("allow_value", ""),
                      ignore_case=bool(self.cfg.get("ignore_case", True)),
                      ordered=bool(self.latest_by), on_missing=self.on_missing)

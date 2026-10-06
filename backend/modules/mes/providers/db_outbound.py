"""MES outbound against a customer database — ONE table, one row per run.

The row is the report HEADER (DUT metadata, no per-test data — see `db_schema.MES_FIELDS`). The target
table is either created from that schema or an existing customer table whose columns are mapped
(`column_map`: MES field -> column name; auto-matched by name, remappable, optional fields skippable).

Config (`outbound`):
    connection       resolved connection dict (the module substitutes the inbound one for same_as_inbound)
    database, table  target ('schema.table' for non-default schemas)
    column_map       {field: column}; empty = same names as the fields

`publish()` writes immediately and idempotently (delete by `run_id`, then insert, one transaction) and
RAISES on any failure — the caller turns that into a loud alert. It never creates anything: creating
the table / adding columns is an explicit operator action (`ensure`).
"""

from __future__ import annotations

import asyncio
import re

from sqlalchemy import Column, delete, insert, inspect, text
from sqlalchemy.schema import CreateColumn

from core.services import dbconn
from modules.mes.providers import db_schema as S

_TABLE_RE = re.compile(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)?")
_COL_RE = re.compile(r"[A-Za-z0-9_ ]+")


class DbOutbound:
    def __init__(self, cfg: dict, *, timeout: float = 10.0) -> None:
        self.cfg = cfg or {}
        self.timeout = timeout
        self._engine = None
        self._kinds: dict[str, str] | None = None

    # --- config ----------------------------------------------------------------------------

    @property
    def column_map(self) -> dict[str, str]:
        cm = {k: v for k, v in (self.cfg.get("column_map") or {}).items() if v}
        return cm or S.default_map()

    def problem(self) -> str | None:
        c = self.cfg
        if not (c.get("connection") or {}).get("provider"):
            return "no database server configured"
        if c["connection"].get("provider") != "sqlite" and not c.get("database"):
            return "database not chosen"
        if not c.get("table"):
            return "table not chosen"
        unmapped = [r for r in S.REQUIRED if not self.column_map.get(r)]
        if unmapped:
            return f"required field(s) not mapped: {', '.join(unmapped)}"
        return None

    def describe(self) -> dict:
        return {"database": self.cfg.get("database"), "table": self.cfg.get("table"),
                "ready": self.problem() is None, "problem": self.problem()}

    def _eng(self):
        if self._engine is None:
            self._engine = dbconn.make_engine(self.cfg["connection"], self.cfg.get("database"),
                                              connect_timeout=min(self.timeout, 8))
        return self._engine

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._kinds = None

    # --- write -----------------------------------------------------------------------------

    def _column_kinds(self) -> dict[str, str]:
        """{column(lower): datetime|date|other} of the target, cached; {} if the catalog can't be read."""
        if self._kinds is None:
            try:
                schema, t = dbconn.split_table(self.cfg["table"])
                cols = inspect(self._eng()).get_columns(t, schema=schema)
                self._kinds = {c["name"].lower(): S.kind_of(c["type"]) for c in cols}
            except Exception:  # noqa: BLE001 — coercion is best effort; the write reports real errors
                self._kinds = {}
        return self._kinds

    def _write(self, row: dict) -> None:
        cm = self.column_map
        tbl = dbconn.lw_table(self.cfg["table"], list(cm.values()))
        kinds = self._column_kinds()
        values = {}
        for f in S.MES_FIELDS:
            col = cm.get(f.name)
            if col:
                values[col] = S.coerce(f, row.get(f.name), kinds.get(col.lower(), "other"))
        with self._eng().begin() as c:
            c.execute(delete(tbl).where(tbl.c[cm["run_id"]] == row["run_id"]))   # idempotent re-send
            c.execute(insert(tbl).values(values))

    async def publish(self, row: dict) -> None:
        problem = self.problem()
        if problem:
            raise dbconn.DbError(f"MES outbound database is not configured ({problem})")
        if not row.get("run_id"):
            raise dbconn.DbError("cannot send a result without a run id")
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(None, self._write, row), self.timeout)
        except asyncio.TimeoutError as exc:
            self.dispose()
            raise dbconn.DbError(f"MES database did not answer within {self.timeout:g} s") from exc
        except Exception:
            self.dispose()                       # drop a possibly dead pooled connection
            raise

    # --- validate / ensure (explicit operator actions) ---------------------------------------

    def validate(self) -> dict:
        """Does the target table fit? -> {ok, exists, columns, map, missing, unmapped_required, blocking, detail}"""
        cm = self.column_map
        out = {"ok": False, "exists": False, "map": cm, "columns": [], "missing": [],
               "unmapped_required": [r for r in S.REQUIRED if not cm.get(r)], "blocking": [], "detail": ""}
        try:
            if not self.cfg.get("table"):
                out["detail"] = "table not chosen"
                return out
            schema, t = dbconn.split_table(self.cfg["table"])
            eng = dbconn.make_engine(self.cfg["connection"], self.cfg.get("database"), connect_timeout=8)
            try:
                insp = inspect(eng)
                out["exists"] = insp.has_table(t, schema=schema)
                if not out["exists"]:
                    out["detail"] = "table does not exist yet — it will be created with the report header schema"
                    out["ok"] = not out["unmapped_required"]
                    return out
                cols = insp.get_columns(t, schema=schema)
            finally:
                eng.dispose()
            have = {c["name"].lower(): c for c in cols}
            out["columns"] = [c["name"] for c in cols]
            out["missing"] = [{"field": f, "column": col} for f, col in cm.items()
                              if col.lower() not in have]
            mapped = {col.lower() for col in cm.values()}
            out["blocking"] = [c["name"] for c in cols
                               if not c.get("nullable", True) and c.get("default") is None
                               and not (c.get("autoincrement") or c.get("identity") or c.get("computed"))
                               and c["name"].lower() not in mapped]
            out["ok"] = not (out["missing"] or out["unmapped_required"] or out["blocking"])
            if out["ok"]:
                out["detail"] = "table fits"
            else:
                bits = []
                if out["unmapped_required"]:
                    bits.append(f"map the required field(s): {', '.join(out['unmapped_required'])}")
                if out["missing"]:
                    bits.append("missing column(s): " + ", ".join(m["column"] for m in out["missing"]))
                if out["blocking"]:
                    bits.append("NOT NULL column(s) with no default that are not mapped: "
                                + ", ".join(out["blocking"]))
                out["detail"] = "; ".join(bits)
        except Exception as exc:  # noqa: BLE001 — honest verdict
            out["ok"], out["detail"] = False, dbconn.short_error(exc)
        return out

    def ensure(self, *, add_missing: bool = False) -> dict:
        """Create the database (MySQL/SQL Server) and the table if absent; optionally add missing
        mapped columns. Returns validate()'s verdict. Explicit operator action — never run by publish."""
        cm = self.column_map
        table = self.cfg.get("table") or ""
        if not _TABLE_RE.fullmatch(table):
            raise dbconn.DbError("table name may only contain letters, digits and underscore "
                                 "(optionally schema.table)")
        bad = [c for c in cm.values() if not _COL_RE.fullmatch(c)]
        if bad:
            raise dbconn.DbError(f"invalid column name(s): {', '.join(bad)}")
        if self.cfg.get("database"):
            dbconn.ensure_database(self.cfg["connection"], self.cfg["database"])
        eng = dbconn.make_engine(self.cfg["connection"], self.cfg.get("database"), connect_timeout=8)
        try:
            schema, t = dbconn.split_table(table)
            insp = inspect(eng)
            if not insp.has_table(t, schema=schema):
                S.build_table(table, cm).create(eng)
            elif add_missing:
                have = {c["name"].lower() for c in insp.get_columns(t, schema=schema)}
                prep = eng.dialect.identifier_preparer
                tname = prep.format_table(dbconn.lw_table(table, []))
                with eng.begin() as c:
                    for f in S.MES_FIELDS:
                        col = cm.get(f.name)
                        if col and col.lower() not in have:
                            ddl = str(CreateColumn(Column(col, f.type)).compile(dialect=eng.dialect))
                            c.execute(text(f"ALTER TABLE {tname} ADD {ddl}"))
        finally:
            eng.dispose()
        self.dispose()
        return self.validate()

"""Writes the Okaya wide row into the customer's table — synchronous SQLAlchemy Core (run in an executor).

Only `core.services.dbconn` is used (it exists so a module can talk to a customer database without
importing another module). Nothing here creates or alters anything except `ensure()`, which is an explicit
operator action — `write_row()` only ever deletes + inserts the one run's row.

Idempotent: the customer's table has no run id, so a row is identified by `(serial_no, date_time)` — the run's
serial and its FINISH time, both stable across a retry. A retry therefore replaces the row it wrote before
instead of duplicating it (delete + insert in one transaction). Re-testing the same serial later has a
different finish time, so it correctly adds a new row.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, MetaData, String, Table, delete, inspect, insert
from sqlalchemy.sql import sqltypes

from core.services import dbconn
from modules.okaya_mes import rowbuilder as rb


def table_def(table: str) -> Table:
    """The customer's table as this module writes it (also what `ensure()` creates when it is absent)."""
    schema, t = dbconn.split_table(table)
    cols = [Column(c, DateTime) if c in rb.DATETIME_COLUMNS else Column(c, String(rb.TEXT_LEN)) for c in rb.COLUMNS]
    return Table(t, MetaData(), *cols, schema=schema)


def write_row(engine, table: str, row: dict) -> None:
    """Replace-then-insert one run's row, atomically. Raises on any failure (the caller makes it loud)."""
    if not row.get("serial_no") or row.get("date_time") is None:
        raise dbconn.DbError("cannot write a result without a serial number and a finish time")
    tbl = table_def(table)
    with engine.begin() as c:
        c.execute(delete(tbl).where(tbl.c.serial_no == row["serial_no"], tbl.c.date_time == row["date_time"]))
        c.execute(insert(tbl).values({k: row.get(k) for k in rb.COLUMNS}))


def validate(conn: dict, database: str | None, table: str) -> dict:
    """Does the target table fit? -> {ok, exists, columns, missing, wrong_type, blocking, detail}.
    `blocking` = NOT NULL columns without a default that this module never fills (an insert would fail)."""
    out = {"ok": False, "exists": False, "columns": [], "missing": [], "wrong_type": [], "blocking": [],
           "detail": ""}
    try:
        if not table:
            out["detail"] = "table not chosen"
            return out
        schema, t = dbconn.split_table(table)
        eng = dbconn.make_engine(conn, database, connect_timeout=8)
        try:
            insp = inspect(eng)
            out["exists"] = insp.has_table(t, schema=schema)
            if not out["exists"]:
                out["detail"] = "table does not exist yet — use Create table to make it with the Okaya layout"
                return out
            cols = insp.get_columns(t, schema=schema)
        finally:
            eng.dispose()
        have = {c["name"].lower(): c for c in cols}
        out["columns"] = [c["name"] for c in cols]
        out["missing"] = [c for c in rb.COLUMNS if c.lower() not in have]
        out["wrong_type"] = [c for c in rb.DATETIME_COLUMNS
                             if c.lower() in have and not isinstance(have[c.lower()]["type"], sqltypes.DateTime)]
        mine = {c.lower() for c in rb.COLUMNS}
        out["blocking"] = [c["name"] for c in cols
                           if not c.get("nullable", True) and c.get("default") is None
                           and not (c.get("autoincrement") or c.get("identity") or c.get("computed"))
                           and c["name"].lower() not in mine]
        out["ok"] = not (out["missing"] or out["wrong_type"] or out["blocking"])
        bits = []
        if out["missing"]:
            bits.append("missing column(s): " + ", ".join(out["missing"]))
        if out["wrong_type"]:
            bits.append("must be a datetime column: " + ", ".join(out["wrong_type"]))
        if out["blocking"]:
            bits.append("NOT NULL column(s) this module never fills: " + ", ".join(out["blocking"]))
        out["detail"] = "table fits the Okaya layout" if out["ok"] else "; ".join(bits)
    except Exception as exc:  # noqa: BLE001 — an honest verdict, never a 500
        out["ok"], out["detail"] = False, dbconn.short_error(exc)
    return out


def ensure(conn: dict, database: str | None, table: str) -> dict:
    """Create the database (MySQL / SQL Server) and the table if absent. Never alters an existing table."""
    if not dbconn.split_table(table)[1] or not all(ch.isalnum() or ch in "._" for ch in table):
        raise dbconn.DbError("table name may only contain letters, digits and underscore (optionally schema.table)")
    if database:
        dbconn.ensure_database(conn, database)
    eng = dbconn.make_engine(conn, database, connect_timeout=8)
    try:
        schema, t = dbconn.split_table(table)
        if not inspect(eng).has_table(t, schema=schema):
            table_def(table).create(eng)
    finally:
        eng.dispose()
    return validate(conn, database, table)

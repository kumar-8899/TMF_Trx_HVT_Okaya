"""MES outbound row schema — the report HEADER (DUT metadata, no per-test data), one row per run.

One registry drives table creation, validation, column mapping and value coercion, so adding a
field to the MES row is one line here. Types mirror `tmf_report` (modules/report/store/schema.py).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from sqlalchemy import Column, Float, Index, Integer, MetaData, String, Table
from sqlalchemy.sql import sqltypes

from core.services.dbconn import split_table


@dataclass(frozen=True)
class MesField:
    name: str
    type: object            # SQLAlchemy type used when the table is CREATED
    required: bool = False  # must be mapped to a column (run_id keys the idempotent write)
    kind: str = "text"      # text | number | epoch | day  (drives coercion to a customer's column type)


MES_FIELDS: tuple[MesField, ...] = (
    MesField("run_id", String(64), required=True),
    MesField("station", String(64)),
    MesField("serial_no", String(128), required=True),
    MesField("model", String(128)),
    MesField("operator", String(128)),
    MesField("recipe_id", String(128)),
    MesField("recipe_version", Integer, kind="number"),
    MesField("result", String(32), required=True),
    MesField("started_ts", Float, kind="epoch"),
    MesField("finished_ts", Float, kind="epoch"),
    MesField("business_day", String(10), kind="day"),
    MesField("shift_label", String(64)),
    MesField("created_at", Float, kind="epoch"),
)
FIELD_BY_NAME = {f.name: f for f in MES_FIELDS}
REQUIRED = tuple(f.name for f in MES_FIELDS if f.required)


def _type_name(t) -> str:
    t = sqltypes.to_instance(t)
    n = getattr(t, "length", None)
    return f"{type(t).__name__.upper()}({n})" if n else type(t).__name__.upper()


def catalog() -> list[dict]:
    """What the UI shows for a to-be-created table / the mapping step."""
    return [{"name": f.name, "required": f.required, "type": _type_name(f.type)} for f in MES_FIELDS]


def default_map() -> dict[str, str]:
    return {f.name: f.name for f in MES_FIELDS}


def auto_map(existing_columns: list[str]) -> dict[str, str | None]:
    """Match each MES field to a column of an existing table by name (case-insensitive)."""
    lower = {c.lower(): c for c in existing_columns}
    return {f.name: lower.get(f.name.lower()) for f in MES_FIELDS}


def build_table(name: str, column_map: dict[str, str]) -> Table:
    """The CREATE-able table for `name` using the mapped column names (new-table case)."""
    schema, t = split_table(name)
    cols = []
    for f in MES_FIELDS:
        col = column_map.get(f.name)
        if col:
            cols.append(Column(col, f.type, primary_key=(f.name == "run_id")))
    tbl = Table(t, MetaData(), *cols, schema=schema)
    sn = column_map.get("serial_no")
    if sn:
        Index(f"ix_{t}_{sn}"[:60], tbl.c[sn])
    return tbl


def kind_of(sa_type) -> str:
    """Coarse kind of an existing column's type, for coercing epoch/day values."""
    if isinstance(sa_type, sqltypes.DateTime):
        return "datetime"
    if isinstance(sa_type, sqltypes.Date):
        return "date"
    return "other"


def coerce(field: MesField, value, target_kind: str):
    """Epoch floats -> datetime for DATETIME columns; business_day text -> date for DATE/DATETIME
    columns. Everything else is written as-is (the driver converts numbers to text columns)."""
    if value is None:
        return None
    if field.kind == "epoch" and target_kind in ("datetime", "date"):
        try:
            d = _dt.datetime.fromtimestamp(float(value))
        except (TypeError, ValueError, OSError, OverflowError):
            return None
        return d if target_kind == "datetime" else d.date()
    if field.kind == "day" and target_kind in ("datetime", "date"):
        try:
            d = _dt.date.fromisoformat(str(value))
        except ValueError:
            return None
        return _dt.datetime(d.year, d.month, d.day) if target_kind == "datetime" else d
    return value

"""Relational report schema (SQLAlchemy Core — MySQL / SQL Server / sqlite for tests).

Normalized so per-application test parameters are ROWS, not columns: a `report`
header + a `report_result` child (one row per test/parameter). No per-app DDL.
Explicit string lengths so MySQL + SQL Server accept the DDL.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger, Column, Float, ForeignKey, Index, Integer, MetaData, String, Table,
)

metadata = MetaData()

report = Table(
    "report", metadata,
    Column("run_id", String(64), primary_key=True),
    Column("station", String(64)),
    Column("serial_no", String(128)),
    Column("model", String(128)),
    Column("operator", String(128)),
    Column("recipe_id", String(128)),
    Column("recipe_version", Integer),
    Column("result", String(32)),
    Column("started_ts", Float),
    Column("finished_ts", Float),
    Column("business_day", String(10)),
    Column("shift_label", String(64)),
    Column("created_at", Float),
    Index("ix_report_business_day", "business_day"),
    Index("ix_report_model", "model"),
    Index("ix_report_shift", "shift_label"),
    Index("ix_report_result", "result"),
    Index("ix_report_started", "started_ts"),
)

report_result = Table(
    "report_result", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("run_id", String(64), ForeignKey("report.run_id", ondelete="CASCADE")),
    Column("seq", Integer),
    Column("test_name", String(255)),
    Column("test_group", String(128)),
    Column("expected", String(255)),
    Column("measured", String(255)),
    Column("result", String(32)),
    Column("unit", String(64)),
    Column("cycle_time_ms", Float),
    Index("ix_result_run", "run_id"),
    Index("ix_result_test", "test_name"),
)

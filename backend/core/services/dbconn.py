"""dbconn — relational database plumbing shared by modules (MySQL / SQL Server / sqlite for tests).

Lifted out of the report store so a second module (MES) can talk to a customer database without
importing the report module (modules depend only on core). Everything here is SYNCHRONOUS SQLAlchemy
Core; callers run it in a thread executor. Drivers (PyMySQL, pyodbc) are imported lazily by
SQLAlchemy on connect, so the app boots without them and a missing driver is reported clearly.

A connection is a plain dict (what the Settings UI stores):
    {provider: mysql|sqlserver|sqlite, host, port, user, password, odbc_driver, path, database}
`database` may also be passed separately — a connection to a server is useful before a database is chosen.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import column, create_engine, desc, select, table, text
from sqlalchemy.engine import URL

PROVIDERS = ("mysql", "sqlserver", "sqlite")
_SYSTEM_DBS = {"information_schema", "mysql", "performance_schema", "sys",
               "master", "tempdb", "model", "msdb"}
_IDENT = re.compile(r"[A-Za-z0-9_]+")


class DbError(Exception):
    """Misconfiguration / connection failure — message is safe to show the user."""


def short_error(exc: BaseException, limit: int = 300) -> str:
    """First line of a driver error (they are multi-line and noisy), truncated."""
    if isinstance(exc, ModuleNotFoundError):
        return f"driver not installed: {exc}"
    return (str(exc).strip().splitlines() or [exc.__class__.__name__])[0][:limit]


# --- URLs + engines ---------------------------------------------------------------------------

def build_url(cfg: dict, database: str | None = None) -> URL:
    p = (cfg or {}).get("provider")
    user, pw, host = cfg.get("user"), cfg.get("password"), cfg.get("host")
    db = database if database is not None else cfg.get("database")
    if p == "mysql":
        return URL.create("mysql+pymysql", username=user, password=pw, host=host,
                          port=int(cfg.get("port") or 3306), database=db or None)
    if p == "sqlserver":
        q = {"driver": cfg.get("odbc_driver") or "ODBC Driver 18 for SQL Server",
             "TrustServerCertificate": "yes"}
        return URL.create("mssql+pyodbc", username=user, password=pw, host=host,
                          port=int(cfg.get("port") or 1433), database=db or "master", query=q)
    if p == "sqlite":     # tests / local file
        return URL.create("sqlite", database=cfg.get("path") or ":memory:")
    raise DbError(f"unknown DB provider '{p}'")


def make_engine(cfg: dict, database: str | None = None, *, connect_timeout: float | None = None):
    url = build_url(cfg, database)
    kw: dict[str, Any] = {"pool_pre_ping": True, "future": True}
    if url.get_backend_name() == "sqlite":
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw["pool_recycle"] = 1800
        if connect_timeout:                       # an operator gate must never hang on a dead server
            kw["connect_args"] = ({"connect_timeout": int(connect_timeout)}
                                  if url.get_backend_name() == "mysql"
                                  else {"timeout": int(connect_timeout)})
    return create_engine(url, **kw)


def build_server_url(cfg: dict) -> URL:
    """Like build_url but WITHOUT the target database — connects at server level so a missing
    database can be created (SQL Server connects via `master`)."""
    p = (cfg or {}).get("provider")
    if p not in ("mysql", "sqlserver"):
        raise DbError(f"cannot auto-create for provider '{p}'")
    return build_url(cfg, database="" if p == "mysql" else "master")


def valid_identifier(name: str | None) -> bool:
    return bool(name) and _IDENT.fullmatch(name) is not None


def ensure_database(cfg: dict, database: str | None = None) -> None:
    """Create the database if it doesn't exist (MySQL / SQL Server); SQLite makes its own file.
    Idempotent. DDL can't be parameterized, so the name is validated to a safe identifier first."""
    p = (cfg or {}).get("provider")
    db = database if database is not None else (cfg or {}).get("database")
    if p not in ("mysql", "sqlserver") or not db:
        return
    if not valid_identifier(db):
        raise DbError(f"invalid database name '{db}' (letters, digits, underscore only)")
    eng = create_engine(build_server_url(cfg), future=True, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as c:
            if p == "mysql":
                c.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db}` "
                               "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            else:  # sqlserver
                c.execute(text(f"IF DB_ID(N'{db}') IS NULL EXEC('CREATE DATABASE [{db}]')"))
    except ModuleNotFoundError:
        raise                                       # driver missing — reported upstream
    except Exception as exc:  # noqa: BLE001
        raise DbError(
            f"database '{db}' does not exist and could not be created automatically "
            f"({short_error(exc, 200)}). Create it manually, or grant the configured "
            "user CREATE privilege.") from exc
    finally:
        eng.dispose()


# --- connection test ---------------------------------------------------------------------------

def connect_check(cfg: dict, database: str | None = None, *, connect_timeout: float | None = 8) -> dict:
    """Connect + SELECT 1. Never creates anything. -> {ok, status: pass|fail|error, detail}."""
    try:
        eng = make_engine(cfg, database, connect_timeout=connect_timeout)
    except ModuleNotFoundError as exc:              # DBAPI driver missing
        return {"ok": False, "status": "error", "detail": short_error(exc)}
    except DbError as exc:
        return {"ok": False, "status": "error", "detail": str(exc)}
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return {"ok": True, "status": "pass", "detail": "connected"}
    except ModuleNotFoundError as exc:
        return {"ok": False, "status": "error", "detail": short_error(exc)}
    except Exception as exc:  # noqa: BLE001 — honest failure verdict
        return {"ok": False, "status": "fail", "detail": short_error(exc)}
    finally:
        eng.dispose()


# --- discovery (what does this server offer?) --------------------------------------------------

def list_databases(cfg: dict, *, connect_timeout: float | None = 8) -> list[str]:
    """Databases visible to the configured user (system databases hidden)."""
    p = cfg.get("provider")
    if p == "sqlite":
        from pathlib import Path
        return [Path(cfg.get("path") or "main").stem or "main"]
    eng = make_engine(cfg, "" if p == "mysql" else "master", connect_timeout=connect_timeout)
    try:
        with eng.connect() as c:
            if p == "mysql":
                names = [r[0] for r in c.execute(text("SHOW DATABASES")).all()]
            else:
                names = [r[0] for r in c.execute(text(
                    "SELECT name FROM sys.databases WHERE database_id > 4 "
                    "AND state_desc = 'ONLINE' AND HAS_DBACCESS(name) = 1 ORDER BY name")).all()]
        return sorted((n for n in names if n and n.lower() not in _SYSTEM_DBS), key=str.lower)
    finally:
        eng.dispose()


def split_table(name: str) -> tuple[str | None, str]:
    """'schema.table' -> (schema, table); plain 'table' -> (None, table). SQL Server tables outside
    `dbo` (and cross-schema MES views) are addressed this way."""
    if "." in name:
        schema, _, t = name.rpartition(".")
        return (schema or None), t
    return None, name


def list_tables(cfg: dict, database: str | None, *, connect_timeout: float | None = 8) -> list[str]:
    """Tables AND views (MES sources are often views). SQL Server names outside dbo are 'schema.table'."""
    p = cfg.get("provider")
    eng = make_engine(cfg, database, connect_timeout=connect_timeout)
    try:
        with eng.connect() as c:
            if p == "mysql":
                if not database and not cfg.get("database"):
                    raise DbError("choose a database first")
                rows = c.execute(text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() "
                    "ORDER BY table_name")).all()
                return [r[0] for r in rows]
            if p == "sqlserver":
                rows = c.execute(text(
                    "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "ORDER BY TABLE_SCHEMA, TABLE_NAME")).all()
                return [t if s == "dbo" else f"{s}.{t}" for s, t in rows]
            rows = c.execute(text("SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                                  "AND name NOT LIKE 'sqlite_%' ORDER BY name")).all()
            return [r[0] for r in rows]
    finally:
        eng.dispose()


def list_columns(cfg: dict, database: str | None, tbl: str, *,
                 connect_timeout: float | None = 8) -> list[dict]:
    """[{name, type, nullable}] of a table or view."""
    from sqlalchemy import inspect
    schema, t = split_table(tbl)
    eng = make_engine(cfg, database, connect_timeout=connect_timeout)
    try:
        cols = inspect(eng).get_columns(t, schema=schema)
        if not cols:
            raise DbError(f"table '{tbl}' not found or has no visible columns")
        return [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True))}
                for c in cols]
    finally:
        eng.dispose()


# --- lightweight (non-reflected) statements: work with names the user typed ---------------------

def lw_table(tbl: str, columns: list[str]):
    """A SQLAlchemy `table()` with the named columns — correctly quoted per dialect, parameterised,
    and needs NO reflection, so it works with names typed by hand when listing isn't permitted."""
    schema, t = split_table(tbl)
    return table(t, *[column(c) for c in dict.fromkeys(columns)], schema=schema)


def distinct_values(cfg: dict, database: str | None, tbl: str, col: str, *, limit: int = 50,
                    connect_timeout: float | None = 8) -> list[str]:
    t = lw_table(tbl, [col])
    eng = make_engine(cfg, database, connect_timeout=connect_timeout)
    try:
        with eng.connect() as c:
            rows = c.execute(select(t.c[col]).distinct().limit(limit)).all()
        return sorted({str(r[0]) for r in rows if r[0] is not None}, key=str.lower)
    finally:
        eng.dispose()


def probe(cfg: dict, database: str | None, tbl: str, cols: list[str], *,
          connect_timeout: float | None = 8) -> None:
    """SELECT <cols> FROM <table> (one row). Raises on a bad name — verifies manually typed names."""
    t = lw_table(tbl, cols)
    eng = make_engine(cfg, database, connect_timeout=connect_timeout)
    try:
        with eng.connect() as c:
            c.execute(select(*[t.c[x] for x in dict.fromkeys(cols)]).limit(1)).all()
    finally:
        eng.dispose()


def order_desc(t, cols: list[str]):
    return [desc(t.c[c]) for c in cols]

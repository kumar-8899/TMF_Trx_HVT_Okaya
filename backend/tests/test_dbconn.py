"""core.services.dbconn — URL/engine building and the dialect-specific discovery SQL.

MySQL / SQL Server are not available in CI, so the server-specific statements are asserted at SQL-string
level through a fake engine; sqlite exercises the real execution path. Verify on the real servers
(Config → MES → Test connection / lists) before trusting a release.
"""

import contextlib

import pytest
from sqlalchemy.dialects import mssql, mysql

from core.services import dbconn
from core.services.dbconn import DbError


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeEngine:
    """Records every statement; answers from a canned list keyed by a substring of the SQL."""

    def __init__(self, answers):
        self.answers, self.sql, self.disposed = answers, [], False

    @contextlib.contextmanager
    def connect(self):
        eng = self

        class _C:
            def execute(self, stmt, *a, **k):
                s = str(stmt)
                eng.sql.append(s)
                for key, rows in eng.answers.items():
                    if key in s:
                        return _Rows(rows)
                return _Rows([])
        yield _C()

    def dispose(self):
        self.disposed = True


def _patch_engine(monkeypatch, answers):
    eng = FakeEngine(answers)
    monkeypatch.setattr(dbconn, "make_engine", lambda *a, **k: eng)
    return eng


# --- URLs ---------------------------------------------------------------------------------------

def test_build_url_per_provider_and_database_override():
    my = dbconn.build_url({"provider": "mysql", "host": "h", "user": "u", "password": "p", "database": "d"})
    assert my.drivername == "mysql+pymysql" and my.port == 3306 and my.database == "d"
    assert dbconn.build_url({"provider": "mysql", "host": "h", "database": "d"}, database="x").database == "x"
    assert dbconn.build_url({"provider": "mysql", "host": "h"}, database="").database is None
    ms = dbconn.build_url({"provider": "sqlserver", "host": "h", "port": "1444"})
    assert ms.drivername == "mssql+pyodbc" and ms.port == 1444 and ms.database == "master"
    assert ms.query["driver"] == "ODBC Driver 18 for SQL Server"
    assert dbconn.build_url({"provider": "sqlite", "path": "x.db"}).database == "x.db"
    with pytest.raises(DbError):
        dbconn.build_url({"provider": "oracle"})


def test_special_characters_in_password_are_escaped_not_injected():
    u = dbconn.build_url({"provider": "mysql", "host": "h", "user": "u", "password": "p@ss/w:rd?#"})
    assert u.password == "p@ss/w:rd?#"
    assert "p@ss/w:rd" not in u.render_as_string(hide_password=True)


def test_connect_timeout_is_passed_per_driver(monkeypatch):
    seen = {}
    monkeypatch.setattr(dbconn, "create_engine", lambda url, **kw: seen.update(kw) or object())
    dbconn.make_engine({"provider": "mysql", "host": "h"}, connect_timeout=5)
    assert seen["connect_args"] == {"connect_timeout": 5}
    dbconn.make_engine({"provider": "sqlserver", "host": "h"}, connect_timeout=5)
    assert seen["connect_args"] == {"timeout": 5}
    seen.clear()
    dbconn.make_engine({"provider": "mysql", "host": "h"})        # report store: no timeout argument
    assert "connect_args" not in seen


# --- discovery SQL --------------------------------------------------------------------------------

def test_list_databases_mysql_hides_system_databases(monkeypatch):
    eng = _patch_engine(monkeypatch, {"SHOW DATABASES": [("information_schema",), ("Mes",), ("mysql",),
                                                         ("performance_schema",), ("sys",), ("alpha",)]})
    assert dbconn.list_databases({"provider": "mysql"}) == ["alpha", "Mes"]
    assert eng.sql == ["SHOW DATABASES"] and eng.disposed


def test_list_databases_sqlserver_uses_sys_databases_with_access_check(monkeypatch):
    eng = _patch_engine(monkeypatch, {"sys.databases": [("MesDb",), ("master",), ("Plant",)]})
    assert dbconn.list_databases({"provider": "sqlserver"}) == ["MesDb", "Plant"]
    sql = eng.sql[0]
    assert "HAS_DBACCESS" in sql and "database_id > 4" in sql and "ONLINE" in sql


def test_list_tables_sqlserver_qualifies_non_dbo_schemas(monkeypatch):
    _patch_engine(monkeypatch, {"INFORMATION_SCHEMA.TABLES": [("dbo", "Units"), ("mes", "Status"),
                                                              ("dbo", "vw_Result")]})
    assert dbconn.list_tables({"provider": "sqlserver"}, "MesDb") == ["Units", "mes.Status", "vw_Result"]


def test_list_tables_mysql_scopes_to_the_connected_database(monkeypatch):
    eng = _patch_engine(monkeypatch, {"information_schema.tables": [("a",), ("b",)]})
    assert dbconn.list_tables({"provider": "mysql", "database": "mes"}, "mes") == ["a", "b"]
    assert "DATABASE()" in eng.sql[0]
    with pytest.raises(DbError, match="choose a database"):
        dbconn.list_tables({"provider": "mysql"}, None)


def test_split_table():
    assert dbconn.split_table("t") == (None, "t")
    assert dbconn.split_table("mes.Status") == ("mes", "Status")


def test_lightweight_table_quotes_per_dialect_and_parameterises():
    from sqlalchemy import select
    t = dbconn.lw_table("mes.Unit Status", ["Serial No", "state"])
    q = select(t.c["state"]).where(t.c["Serial No"] == "x' OR 1=1 --").limit(1)
    ms = str(q.compile(dialect=mssql.dialect()))
    assert "[Serial No]" in ms and "mes.[Unit Status]" in ms and "TOP" in ms and "OR 1=1" not in ms
    my = q.compile(dialect=mysql.dialect())
    assert "`Serial No`" in str(my) and "LIMIT" in str(my) and "OR 1=1" not in str(my)
    assert "x' OR 1=1 --" in my.params.values()


# --- database creation guard ---------------------------------------------------------------------

def test_ensure_database_validates_names_and_skips_sqlite():
    dbconn.ensure_database({"provider": "sqlite"}, "anything")         # no-op
    with pytest.raises(DbError, match="invalid database name"):
        dbconn.ensure_database({"provider": "mysql", "host": "h"}, "x`; DROP DATABASE y; --")
    assert dbconn.valid_identifier("Mes_1") and not dbconn.valid_identifier("a-b")


# --- real execution on sqlite ----------------------------------------------------------------------

def test_connect_check_and_listing_on_sqlite(tmp_path):
    path = tmp_path / "x.sqlite"
    cfg = {"provider": "sqlite", "path": str(path)}
    assert dbconn.connect_check(cfg)["ok"]
    bad = dbconn.connect_check({"provider": "sqlite", "path": str(tmp_path / "no" / "dir" / "x.db")})
    assert bad["ok"] is False and bad["status"] == "fail"
    assert dbconn.connect_check({"provider": "nope"})["status"] == "error"

    import sqlite3
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (a TEXT, b INTEGER NOT NULL)")
    con.execute("INSERT INTO t VALUES ('x', 1), ('y', 2), ('x', 3)")
    con.commit(); con.close()                                         # noqa: E702
    assert dbconn.list_tables(cfg, None) == ["t"]
    cols = dbconn.list_columns(cfg, None, "t")
    assert [(c["name"], c["nullable"]) for c in cols] == [("a", True), ("b", False)]
    assert dbconn.distinct_values(cfg, None, "t", "a") == ["x", "y"]
    dbconn.probe(cfg, None, "t", ["a", "b"])
    with pytest.raises(Exception):
        dbconn.probe(cfg, None, "t", ["a", "zzz"])


def test_short_error_is_one_line_and_flags_missing_drivers():
    assert dbconn.short_error(RuntimeError("first line\nsecond line")) == "first line"
    assert dbconn.short_error(ModuleNotFoundError("No module named 'pymysql'")).startswith("driver not installed")
    assert len(dbconn.short_error(RuntimeError("x" * 1000))) == 300

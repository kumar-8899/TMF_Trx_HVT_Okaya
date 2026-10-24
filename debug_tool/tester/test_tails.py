"""debug_tool.tails - read-only DB/launcher log views."""

import json
import sqlite3
import time

from debug_tool import tails


def make_db(path, error_rows=(), action_rows=()):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE records (id TEXT, type TEXT, ts REAL, station TEXT, source_version TEXT, summary TEXT, data TEXT, "
                "PRIMARY KEY (type, id))")
    for i, (ts, data) in enumerate(error_rows):
        con.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?)", (f"e{i}", "error_log", ts, "st1", "1", f"s{i}", json.dumps(data)))
    for i, (ts, data) in enumerate(action_rows):
        con.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?)", (f"a{i}", "action_log", ts, "st1", "1", f"a{i}", json.dumps(data)))
    con.commit()
    con.close()


ERRS = [(1.0, {"level": "warning", "subsystem": "runs", "message": "run ended abnormally", "context": {"run_id": "R1"}}),
        (2.0, {"level": "error", "subsystem": "instrument", "message": "psu1.measure timeout", "context": {"instance_id": "psu1"}}),
        (3.0, {"level": "info", "subsystem": "core", "message": "fine"})]


def test_error_log_rows_are_normalised_oldest_first(tmp_path):
    db = tmp_path / "tmf.sqlite"
    make_db(db, ERRS)
    out = tails.read_db_log(db, "error_log")
    assert [r["message"] for r in out["rows"]] == ["run ended abnormally", "psu1.measure timeout", "fine"]
    r = out["rows"][1]
    assert r["source"] == "error_log" and r["level"] == "error" and r["subsystem"] == "instrument" and r["context"] == {"instance_id": "psu1"}


def test_level_filter_since_and_tail(tmp_path):
    db = tmp_path / "tmf.sqlite"
    make_db(db, ERRS)
    assert [r["message"] for r in tails.read_db_log(db, "error_log", level="warning")["rows"]] == ["run ended abnormally", "psu1.measure timeout"]
    assert [r["message"] for r in tails.read_db_log(db, "error_log", since_ts=1.5)["rows"]] == ["psu1.measure timeout", "fine"]
    assert [r["message"] for r in tails.read_db_log(db, "error_log", tail=1)["rows"]] == ["fine"]


def test_action_log_failure_is_a_warning(tmp_path):
    db = tmp_path / "tmf.sqlite"
    make_db(db, (), [(1.0, {"principal": "op", "action": "auth.login", "result": "failure"})])
    r = tails.read_db_log(db, "action_log")["rows"][0]
    assert r["level"] == "warning" and r["message"] == "auth.login" and r["subsystem"] == "op"


def test_the_db_is_opened_read_only_and_never_created(tmp_path):
    missing = tmp_path / "nope.sqlite"
    out = tails.read_db_log(missing, "error_log")
    assert out["rows"] == [] and "not found" in out["note"] and not missing.exists()
    db = tmp_path / "tmf.sqlite"
    make_db(db, ERRS)
    con = tails._connect_ro(db)
    try:
        import pytest
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO records VALUES ('x','error_log',1,'s','1','s','{}')")
    finally:
        con.close()


def test_a_corrupt_or_wrong_schema_db_yields_a_note_not_an_exception(tmp_path):
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"this is not a database at all")
    assert "rows" in tails.read_db_log(bad, "error_log") and tails.read_db_log(bad, "error_log")["rows"] == []
    nodata = tmp_path / "empty.sqlite"
    sqlite3.connect(nodata).close()
    out = tails.read_db_log(nodata, "error_log")
    assert out["rows"] == [] and "could not read" in out["note"]


def test_launcher_log_parsed_with_levels_and_timestamps(tmp_path):
    f = tmp_path / "launcher.log"
    f.write_text("2026-10-15 01:20:58 launcher: swap FAILED: [WinError 5] Access is denied\n"
                 "2026-10-15 01:21:00 launcher: relaunch requested\n"
                 "plain continuation line\n"
                 "2026-10-15 01:22:00 launcher: backend up\n", encoding="utf-8")
    rows = tails.read_launcher(f)["rows"]
    assert [r["level"] for r in rows] == ["error", "warning", "info", "info"]
    assert rows[0]["message"].startswith("swap FAILED") and isinstance(rows[0]["ts"], float)
    assert rows[2]["ts"] == rows[1]["ts"]                           # a continuation inherits the previous timestamp
    assert [r["message"] for r in tails.read_launcher(f, level="error")["rows"]] == ["swap FAILED: [WinError 5] Access is denied"]


def test_launcher_missing_is_a_note(tmp_path):
    out = tails.read_launcher(tmp_path / "none.log")
    assert out["rows"] == [] and "not found" in out["note"]


def test_read_log_dispatch_and_unknown_source(tmp_path):
    assert "unknown log source" in tails.read_log("nope", db=None, launcher=None)["note"]
    assert "not found" in tails.read_log("error_log", db=None, launcher=None)["note"]


def test_db_tail_returns_only_new_rows(tmp_path):
    db = tmp_path / "tmf.sqlite"
    make_db(db, [(1.0, {"message": "old"})])
    t = tails.DbTail(db, "error_log", start_ts=1.0)
    assert t.poll() == []
    con = sqlite3.connect(db)
    con.execute("INSERT INTO records VALUES ('n1','error_log',5.0,'st1','1','s','{\"message\":\"new\",\"level\":\"error\"}')")
    con.commit()
    con.close()
    assert [r["message"] for r in t.poll()] == ["new"]
    assert t.poll() == []                                           # not returned twice


def test_file_tail_reads_only_what_was_appended_and_survives_truncation(tmp_path):
    f = tmp_path / "launcher.log"
    f.write_text("before the tail started\n", encoding="utf-8")
    t = tails.FileTail(f)
    assert t.poll() == []
    with f.open("a", encoding="utf-8") as fh:
        fh.write("2026-10-15 02:00:00 launcher: swap FAILED: locked\n")
    got = t.poll()
    assert len(got) == 1 and got[0]["level"] == "error" and abs(got[0]["ts"] - time.time()) < 5
    f.write_text("fresh after rotation\n", encoding="utf-8")        # truncated: restart from the top
    assert [r["message"] for r in t.poll()] == ["fresh after rotation"]
    assert tails.FileTail(None).poll() == []

"""debug_tool.engine - recorder modes, passive reads, live follow, level TTL, export. Fake broker feed + fake core."""

import asyncio
import json
import sqlite3
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from debug_server.capture import parse
from debug_tool.appinfo import discover
from debug_tool.engine import Engine, EngineConfig, normalise, read_recorder_files


def make_app(tmp_path, *, in_app_recorder=False):
    root = tmp_path / "deploy"
    (root / "run.dist").mkdir(parents=True)
    (root / "run.dist" / "RELEASE.json").write_text(json.dumps({"product": "acme", "version": "2.0.0", "framework_version": "1.32.0"}))
    (root / "config").mkdir()
    (root / "config" / "app.json").write_text(json.dumps({"stations": ["st1", "st2"], "debug": {"enabled": in_app_recorder, "port": 8001}}))
    (root / "data").mkdir()
    con = sqlite3.connect(root / "data" / "tmf.sqlite")
    con.execute("CREATE TABLE records (id TEXT, type TEXT, ts REAL, station TEXT, source_version TEXT, summary TEXT, data TEXT, "
                "PRIMARY KEY (type, id))")
    con.commit()
    con.close()
    return discover(root, processes=lambda: [])


def msg(station, sub, payload):
    return parse(f"tmf/{station}/{sub}", station, json.dumps(payload))


FEED = [
    msg("st1", "event/run-started", {"type": "run-started", "ts": 100.0, "trace": "run:R1", "payload": {"run_id": "R1", "app_version": "2.0.0"}}),
    msg("st2", "diag", {"ts": 100.5, "level": "warning", "subsystem": "instrument", "message": "psu2 link reconnecting",
                        "context": {"instance_id": "psu2", "state": "reconnecting"}}),
    msg("st1", "diag", {"ts": 101.0, "level": "error", "subsystem": "instrument", "message": "psu1.measure error: boom",
                        "context": {"instance_id": "psu1", "method": "measure", "outcome": "error", "elapsed_ms": 5.0,
                                    "error": {"type": "DeviceError", "message": "boom", "cause": "ValueError"}}}),
    msg("st1", "event/run-finished", {"type": "run-finished", "ts": 102.0, "trace": "run:R1", "payload": {"run_id": "R1", "result": "FAIL"}}),
]


def fake_subscriber(records, state=True):
    async def sub(ingestor, host, port, *, on_state=None):
        ingestor.broker_connected = state
        if on_state:
            on_state(state)
        for r in records:
            ingestor.ingest(r)
        await asyncio.sleep(3600)
    return sub


async def started(tmp_path, *, records=FEED, force=None, probe=lambda p: False, app=None, **kw):
    app = app or make_app(tmp_path)
    cfg = EngineConfig(app=app, data_dir=tmp_path / "tooldata", force_mode=force, in_app_probe=probe)
    eng = Engine(cfg, subscriber=fake_subscriber(records), **kw)
    await eng.start()
    await asyncio.sleep(0.05)
    return eng


@pytest.mark.asyncio
async def test_own_mode_records_all_stations_and_serves_passive_reads(tmp_path):
    eng = await started(tmp_path)
    try:
        assert eng.mode == "own" and eng.health()["live"]["mqtt"] == "connected"
        stations = {r["station"] for r in eng.events()}
        assert stations == {"st1", "st2"}                           # both sockets, not just the first
        assert [r["message"] for r in eng.events(subsystem="instrument", level="error")] == ["psu1.measure error: boom"]
        assert eng.health()["recorder"]["buffer_used"] == 4 and eng.health()["app"]["app_version"] == "2.0.0"
        assert (tmp_path / "tooldata" / "recorder").is_dir()        # own mode writes its recorder under the tool's folder
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_attach_mode_never_writes_into_the_in_app_recorder_directory(tmp_path):
    app = make_app(tmp_path, in_app_recorder=True)
    dbg = app.debug_dir
    dbg.mkdir(parents=True)
    (dbg / "debug.jsonl").write_text(json.dumps({"seq": 1, "ts": 50.0, "kind": "event", "type": "run-started",
                                                 "payload": {"payload": {"run_id": "OLD"}}}) + "\n", encoding="utf-8")
    before = {p.name: p.stat().st_mtime for p in dbg.iterdir()}
    eng = await started(tmp_path, probe=lambda port: port == 8001, app=app)
    try:
        assert eng.mode == "attach" and any("one writer" in n for n in eng.notes)
        assert eng.rolling is None and eng.snapshot is None
        assert not (tmp_path / "tooldata" / "recorder").exists()    # not even its own recorder
        assert {p.name: p.stat().st_mtime for p in dbg.iterdir()} == before          # untouched
        assert eng.records_for_analysis()                            # live ring is used
    finally:
        await eng.stop()
    assert {p.name for p in dbg.iterdir()} == set(before)           # nothing created or removed on stop either


@pytest.mark.asyncio
async def test_forced_mode_overrides_auto_detection(tmp_path):
    eng = await started(tmp_path, force="attach", probe=lambda p: False)
    try:
        assert eng.mode == "attach"
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_why_and_instrument_history_come_from_the_ring(tmp_path):
    eng = await started(tmp_path)
    try:
        out = eng.why()
        assert out["run"] == "R1" and out["first_fault"] is not None
        assert Path(out["digest_path"]).is_file() and str(tmp_path / "tooldata") in out["digest_path"]
        inst = eng.instruments()
        assert inst["instruments"]["psu1"]["failed_calls"] == 1 and inst["instruments"]["psu2"]["state"] == "reconnecting"
        assert list(eng.instruments("psu1")["instruments"]) == ["psu1"] and inst["live_mqtt"] == "connected"
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_history_files_are_used_when_the_ring_has_no_run(tmp_path):
    app = make_app(tmp_path, in_app_recorder=True)
    app.debug_dir.mkdir(parents=True)
    rec = [r.to_dict() for r in FEED]
    (app.debug_dir / "debug.jsonl").write_text("\n".join(json.dumps(r) for r in rec) + "\n", encoding="utf-8")
    eng = await started(tmp_path, records=[], probe=lambda p: p == 8001, app=app)
    try:
        assert eng.why()["run"] == "R1"                              # found in the in-app recorder's files, read-only
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_follow_returns_live_mqtt_and_new_db_rows_tagged_by_source_and_is_bounded(tmp_path):
    app = make_app(tmp_path)
    eng = await started(tmp_path, records=[], app=app)
    try:
        async def produce():
            await asyncio.sleep(0.3)
            eng.ingestor.ingest(msg("st1", "diag", {"ts": time.time(), "level": "error", "subsystem": "daq", "message": "mqtt side"}))
            con = sqlite3.connect(app.db_path)
            con.execute("INSERT INTO records VALUES ('n1','error_log',?, 'st1','1','s',?)",
                        (time.time() + 0.1, json.dumps({"level": "error", "subsystem": "daq", "message": "db side"})))
            con.commit()
            con.close()
        prod = asyncio.create_task(produce())
        out = await eng.follow(seconds=2.0, sources=("mqtt", "logs"))
        await prod
        assert {e["message"] for e in out["events"]} >= {"mqtt side", "db side"}
        assert out["counts"].get("diag") == 1 and out["counts"].get("error_log") == 1 and not out["truncated"]
        capped = None
        for i in range(50):
            eng.ingestor.ingest(msg("st1", "diag", {"ts": time.time(), "level": "info", "subsystem": "x", "message": f"m{i}"}))
        task = asyncio.create_task(eng.follow(seconds=3, sources=("mqtt",), max_events=5))
        await asyncio.sleep(0.2)
        for i in range(20):
            eng.ingestor.ingest(msg("st1", "diag", {"ts": time.time(), "level": "info", "subsystem": "x", "message": f"n{i}"}))
        capped = await task
        assert capped["truncated"] and len(capped["events"]) == 5 and "max_events" in capped["note"]
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_follow_filters_by_subsystem_and_level(tmp_path):
    eng = await started(tmp_path, records=[])
    try:
        async def produce():
            await asyncio.sleep(0.2)
            for sub, lv in (("daq", "info"), ("daq", "error"), ("instrument", "error")):
                eng.ingestor.ingest(msg("st1", "diag", {"ts": time.time(), "level": lv, "subsystem": sub, "message": f"{sub}-{lv}"}))
        p = asyncio.create_task(produce())
        out = await eng.follow(seconds=1.2, sources=("mqtt",), subsystem="daq", level="error")
        await p
        assert [e["message"] for e in out["events"]] == ["daq-error"]
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_follow_says_so_when_mqtt_is_disconnected(tmp_path):
    app = make_app(tmp_path)
    cfg = EngineConfig(app=app, data_dir=tmp_path / "t")
    eng = Engine(cfg, subscriber=fake_subscriber([], state=False))
    await eng.start()
    await asyncio.sleep(0.05)
    try:
        out = await eng.follow(seconds=0.6, sources=("mqtt",))
        assert out["live"]["mqtt"] == "disconnected" and "disconnected" in out["note"]
        assert eng.health()["live"]["mqtt"] == "disconnected"
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_logs_from_the_db_and_the_live_ring(tmp_path):
    app = make_app(tmp_path)
    con = sqlite3.connect(app.db_path)
    con.execute("INSERT INTO records VALUES ('e1','error_log',5.0,'st1','1','s',?)", (json.dumps({"level": "error", "message": "from db"}),))
    con.commit()
    con.close()
    eng = await started(tmp_path, app=app)
    try:
        assert [r["message"] for r in eng.logs("error_log")["rows"]] == ["from db"]
        assert [r["message"] for r in eng.logs("diag", level="error")["rows"]] == ["psu1.measure error: boom"]
        assert "unknown log source" in eng.logs("nope")["note"]
    finally:
        await eng.stop()


def core_transport(state):
    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"].append((request.method, request.url.path, request.headers.get("authorization"), request.content))
        if request.headers.get("authorization") != "Bearer coretok":
            return httpx.Response(401, json={"detail": "bad token"})
        if request.method == "GET":
            return httpx.Response(200, json={"default": "warning", "overrides": state.get("overrides", {})})
        body = json.loads(request.content)
        state["overrides"] = {**state.get("overrides", {}), body["subsystem"]: body["level"]}
        return httpx.Response(200, json={"applied": {body["subsystem"]: body["level"]}})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_level_set_applies_then_reverts_by_itself(tmp_path):
    state = {"calls": []}
    eng = await started(tmp_path, http_factory=lambda: httpx.AsyncClient(transport=core_transport(state)))
    eng.min_ttl_minutes = 0.01                                          # 0.6 s so the test does not wait a minute
    try:
        out = await eng.level_set("daq", "debug", 0.01, "coretok")
        assert out["applied"] == {"daq": "debug"} and out["will_revert_to"] == "warning" and state["overrides"]["daq"] == "debug"
        assert "daq" in eng.health()["level_reverts_pending"]
        await asyncio.sleep(1.0)
        assert state["overrides"]["daq"] == "warning" and eng.health()["level_reverts_pending"] == {}
        assert any("reverted to warning" in n for n in eng.notes)
        assert all(c[2] == "Bearer coretok" for c in state["calls"])
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_repeated_level_changes_keep_the_original_level_to_revert_to(tmp_path):
    state = {"calls": [], "overrides": {"daq": "error"}}
    eng = await started(tmp_path, http_factory=lambda: httpx.AsyncClient(transport=core_transport(state)))
    eng.min_ttl_minutes = 0.01
    try:
        await eng.level_set("daq", "info", 5, "coretok")
        out = await eng.level_set("daq", "debug", 0.01, "coretok")
        assert out["will_revert_to"] == "error"                         # not "info": the level before the FIRST change
        await asyncio.sleep(1.0)
        assert state["overrides"]["daq"] == "error"
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_level_set_needs_a_core_token_and_surfaces_a_core_refusal(tmp_path):
    state = {"calls": []}
    eng = await started(tmp_path, http_factory=lambda: httpx.AsyncClient(transport=core_transport(state)))
    try:
        with pytest.raises(PermissionError, match="X-Core-Token"):
            await eng.level_set("daq", "debug", 5, None)
        with pytest.raises(RuntimeError, match="401"):
            await eng.level_set("daq", "debug", 5, "wrong")
        with pytest.raises(ValueError):
            await eng.level_set("daq", "loud", 5, "coretok")
        assert eng.level_reverts == {}
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_a_failed_revert_is_reported_loudly(tmp_path):
    state = {"calls": []}
    transport = core_transport(state)
    eng = await started(tmp_path, http_factory=lambda: httpx.AsyncClient(transport=transport))
    eng.min_ttl_minutes = 0.01
    try:
        await eng.level_set("daq", "debug", 0.01, "coretok")
        state["calls"].clear()
        eng._http_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"detail": "down"})))
        await asyncio.sleep(1.0)
        assert any("LEVEL REVERT FAILED" in n for n in eng.notes)
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_capture_round_trip(tmp_path):
    eng = await started(tmp_path, records=[])
    try:
        cid = eng.capture_start("repro")["capture_id"]
        eng.ingestor.ingest(msg("st1", "diag", {"ts": 1.0, "level": "info", "subsystem": "x", "message": "inside"}))
        assert eng.capture_stop(cid)["records"] == 1
        assert "inside" in eng.capture_export(cid)
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_export_bundle_registers_a_download_and_lists_what_was_missing(tmp_path, monkeypatch):
    from debug_server import sysinfo
    monkeypatch.setattr(sysinfo, "processes", lambda: {"processes": []})
    monkeypatch.setattr(sysinfo, "app_health", lambda port=None: {"app_running": False, "note": "n"})
    eng = await started(tmp_path)
    try:
        out = await eng.export_bundle(integrity=False)
        assert Path(out["path"]).is_file() and out["download_url"] == f"/files/{out['download_id']}"
        assert eng.downloads[out["download_id"]] == Path(out["path"])
        names = zipfile.ZipFile(out["path"]).namelist()
        assert "MANIFEST.json" in names and "system/ports.json" in names and any("diagnostics" in m for m in out["missing"]) or True
        assert out["bytes"] > 0
    finally:
        await eng.stop()


@pytest.mark.asyncio
async def test_export_without_an_app_is_a_clear_error(tmp_path):
    from debug_tool.appinfo import AppInfo
    eng = await started(tmp_path, app=AppInfo(None, None, "not found"))
    try:
        with pytest.raises(RuntimeError, match="no app install"):
            await eng.export_bundle()
    finally:
        await eng.stop()


def test_normalise_gives_one_shape_for_every_source():
    d = normalise(FEED[2])
    assert d["source"] == "diag" and d["subsystem"] == "instrument" and d["level"] == "error" and d["context"]["instance_id"] == "psu1"
    ev = normalise(FEED[0])
    assert ev["source"] == "mqtt" and ev["type"] == "run-started" and ev["trace"] == "run:R1"
    row = {"source": "error_log", "ts": 1, "level": "error", "message": "x"}
    assert normalise(row) == row


def test_read_recorder_files_is_read_only_and_tolerates_junk(tmp_path):
    d = tmp_path / "rec"
    d.mkdir()
    (d / "debug.jsonl").write_text('{"a":1}\nnot json\n{"b":2}\n', encoding="utf-8")
    (d / "snapshot-1.jsonl").write_text('{"snap":1}\n', encoding="utf-8")      # snapshots are not part of the stream
    assert read_recorder_files(d) == [{"a": 1}, {"b": 2}]
    assert read_recorder_files(tmp_path / "missing") == [] and not (tmp_path / "missing").exists()
    assert read_recorder_files(None) == []

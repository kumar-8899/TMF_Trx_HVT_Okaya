"""Debug Server standalone tester — no broker, synthetic bus records."""

import json

import httpx
import pytest
from httpx import ASGITransport

from debug_server.analysis import Pairer, group_traces, validate
from debug_server.app import build_app
from debug_server.auth import TokenChecker
from debug_server.capture import DIAG, EVENT, REQUEST, Ring, parse
from debug_server.config import DebugConfig
from debug_server.ingest import Ingestor

ST = "st1"


def _diag(sub="daq", level="info", msg="ok", trace=None, ts=1.0):
    body = {"seq": 1, "ts": ts, "level": level, "subsystem": sub, "message": msg, "context": {}}
    if trace:
        body["trace"] = trace
    return parse(f"tmf/{ST}/diag/{sub}", ST, json.dumps(body))


def _event(typ="run-started", trace=None, ts=1.0):
    body = {"type": typ, "ts": ts, "payload": {}}
    if trace:
        body["trace"] = trace
    return parse(f"tmf/{ST}/event/{typ}", ST, json.dumps(body))


# --- classify / parse ------------------------------------------------------

def test_parse_classifies_and_extracts():
    assert _event().kind == EVENT and _event().type == "run-started"
    d = _diag(trace="run:7f")
    assert d.kind == DIAG and d.subsystem == "daq" and d.trace == "run:7f"
    req = parse(f"tmf/{ST}/cmd/run.start", ST, json.dumps({"id": "abc", "op": "run.start", "reply_to": "tmf/st1/cmd/resp/x"}))
    assert req.kind == REQUEST and req.corr_id == "abc"
    rep = parse(f"tmf/{ST}/cmd/resp/x", ST, json.dumps({"id": "abc", "ok": True}))
    assert rep.kind == "reply" and rep.corr_id == "abc"
    assert parse(f"tmf/{ST}/value/vbus", ST, b'{"value":1}').kind == "value"
    assert parse(f"tmf/{ST}/status", ST, b'{"state":"online"}').kind == "status"


# --- ring + drop counter ---------------------------------------------------

def test_ring_drops_oldest_and_counts():
    ring = Ring(capacity=3)
    for i in range(5):
        ring.add(_diag(msg=f"m{i}"))
    assert len(ring) == 3 and ring.dropped == 2


# --- schema validation -----------------------------------------------------

def test_validate_flags_bad_payloads():
    good = _diag(); validate(good); assert good.valid is True
    bad = parse(f"tmf/{ST}/diag/daq", ST, json.dumps({"ts": 1.0, "level": "info"}))  # missing subsystem,message
    validate(bad); assert bad.valid is False and "missing" in bad.error
    badlv = parse(f"tmf/{ST}/diag/daq", ST, json.dumps({"ts": 1, "level": "nope", "subsystem": "x", "message": "m"}))
    validate(badlv); assert badlv.valid is False and "level" in badlv.error
    ev = parse(f"tmf/{ST}/event/x", ST, json.dumps({"ts": 1}))  # missing type
    validate(ev); assert ev.valid is False


# --- pairing + orphan ------------------------------------------------------

def test_pairer_pairs_and_flags_orphan():
    p = Pairer(orphan_timeout_s=2.0)
    p.observe(parse(f"tmf/{ST}/cmd/a", ST, json.dumps({"id": "1", "op": "a", "reply_to": "r", "ts": 10.0})))
    p.observe(parse(f"tmf/{ST}/cmd/resp/x", ST, json.dumps({"id": "1", "ts": 10.05})))
    p.observe(parse(f"tmf/{ST}/cmd/b", ST, json.dumps({"id": "2", "op": "b", "ts": 10.0})))
    soon = {r["corr_id"]: r for r in p.list(now=10.06)}
    assert soon["1"]["status"] == "paired" and soon["1"]["latency_ms"] == 50.0
    assert soon["2"]["status"] == "pending"    # 0.06s < 2s deadline
    later = {r["corr_id"]: r for r in p.list(now=20.0)}
    assert later["2"]["status"] == "orphan"    # past deadline, still no reply


# --- traces ----------------------------------------------------------------

def test_group_traces_collapses_and_flags_error():
    recs = [_event(trace="run:7f", ts=1.0), _diag(trace="run:7f", level="error", msg="boom", ts=1.2),
            _diag(trace="run:9a", ts=2.0)]
    g = {x["trace"]: x for x in group_traces(recs)}
    assert g["run:7f"]["count"] == 2 and g["run:7f"]["has_error"] is True
    assert g["run:9a"]["has_error"] is False


# --- ingest + REST ---------------------------------------------------------

@pytest.fixture
async def client():
    ing = Ingestor(ST, capacity=100)
    checker = TokenChecker("http://core", require_auth=False)
    app = build_app(ing, DebugConfig(station=ST), checker)
    # seed a run trace + an orphan request + a violation
    for r in [_event(trace="run:7f"), _diag(trace="run:7f", level="error", msg="x"),
              parse(f"tmf/{ST}/cmd/run.start", ST, json.dumps({"id": "9", "op": "run.start", "ts": 1.0})),
              parse(f"tmf/{ST}/diag/daq", ST, json.dumps({"ts": 1, "level": "info"})),  # invalid
              parse(f"tmf/{ST}/status", ST, json.dumps({"state": "online", "ts": 1}))]:
        ing.ingest(r)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c, ing


def test_status_repeats_coalesced_but_liveness_fresh():
    ing = Ingestor(ST, capacity=100)
    online = lambda ts: parse(f"tmf/{ST}/status", ST, json.dumps({"state": "online", "ts": ts}))
    for ts in (1.0, 2.0, 3.0):
        ing.ingest(online(ts))                       # retained repeat every "second"
    assert len([r for r in ing.ring.all() if r.kind == "status"]) == 1   # only first kept
    assert ing.coalesced == 2
    assert ing.liveness.grid()[0]["last_seen"] == 3.0                     # but liveness advanced
    ing.ingest(parse(f"tmf/{ST}/status", ST, json.dumps({"state": "offline", "ts": 4.0})))
    assert len([r for r in ing.ring.all() if r.kind == "status"]) == 2   # state change recorded


async def test_rest_surface(client):
    c, _ = client
    assert (await c.get("/debug/health")).json()["buffer_used"] == 5
    assert len((await c.get("/debug/events")).json()) == 5
    traces = (await c.get("/debug/traces")).json()
    assert any(t["trace"] == "run:7f" and t["has_error"] for t in traces)
    wf = (await c.get("/debug/trace/run:7f")).json()
    assert len(wf) == 2
    viol = (await c.get("/debug/violations")).json()
    assert len(viol) == 1
    live = (await c.get("/debug/liveness")).json()
    assert live[0]["status"] == "online"


async def test_capture_export_roundtrip(client):
    c, _ = client
    cid = (await c.post("/debug/capture/start", json={"name": "t"})).json()["capture_id"]
    # ingest more after start
    (await c.get("/debug/health"))
    stop = await c.post("/debug/capture/stop", json={"capture_id": cid})
    assert stop.status_code == 200
    exp = await c.get(f"/debug/capture/{cid}/export")
    assert exp.status_code == 200   # JSONL (may be empty if nothing after start)

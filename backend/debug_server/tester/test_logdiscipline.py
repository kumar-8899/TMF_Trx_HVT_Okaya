"""LogDiscipline (REMOTE_DEBUG.md §4) — never analog per-sample; one summary record
per interval carrying all vars; digital edges + chatter collapse; repeat collapse."""

from debug_server.config import AnalogConfig, DigitalConfig, LimitsConfig
from debug_server.logdiscipline import LogDiscipline, load_variable_meta


def _disc(**kw):
    out: list[dict] = []
    meta = {"vbus": {"deadband": None, "range": (0.0, 20.0)}}  # deadband = 1% * 20 = 0.2
    d = LogDiscipline(AnalogConfig(**kw.get("analog", {})),
                      DigitalConfig(chatter_threshold=5, chatter_window_ms=1000),
                      LimitsConfig(per_type_rate_per_s=1000),
                      meta, out.append)
    return d, out


def _value(name, value, ts):
    return {"kind": "value", "subtopic": f"value/{name}", "ts": ts, "payload": {"value": value}}


def test_flat_rail_writes_nothing_beyond_deadband():
    d, out = _disc()
    d.feed(_value("vbus", 12.0, 100.0), active=False)   # first → one change
    d.feed(_value("vbus", 12.1, 100.05), active=False)  # +0.1 < 0.2 deadband → suppressed
    d.feed(_value("vbus", 12.15, 100.1), active=False)  # still within deadband → suppressed
    d.feed(_value("vbus", 12.5, 100.15), active=False)  # +0.5 > 0.2 → change
    changes = [r for r in out if r["kind"] == "analog-change"]
    assert [c["value"] for c in changes] == [12.0, 12.5]
    assert d.suppressed == 2


def test_periodic_summary_is_one_record_for_all_vars():
    d, out = _disc()
    meta2 = {"vbus": {"deadband": None, "range": (0, 20)}, "temp": {"deadband": None, "range": (0, 100)}}
    d.meta = meta2
    d.feed(_value("vbus", 12.0, 100.0), active=False)   # sets last_summary=100
    d.feed(_value("temp", 30.0, 100.1), active=False)
    d.feed(_value("vbus", 13.0, 102.5), active=False)   # interval (idle 2s) elapsed → flush
    summaries = [r for r in out if r["kind"] == "analog-summary"]
    assert len(summaries) == 1
    assert set(summaries[0]["vars"]) == {"vbus", "temp"}       # ALL vars in ONE record
    assert summaries[0]["vars"]["vbus"]["n"] >= 1


def test_threshold_crossing_emitted():
    d, out = _disc()
    d.feed(_value("vbus", 10.0, 100.0), active=False)   # in range
    d.feed(_value("vbus", 25.0, 100.1), active=False)   # exceed (range max 20)
    d.feed(_value("vbus", 11.0, 100.2), active=False)   # return
    edges = [(r["edge"]) for r in out if r["kind"] == "threshold"]
    assert edges == ["exceed", "return"]


def test_digital_chatter_collapses_a_burst():
    d, out = _disc()
    d.feed(_value("relay", False, 100.0), active=False)   # prime (no edge)
    state = False
    ts = 100.0
    for _ in range(12):
        state = not state
        ts += 0.01
        d.feed(_value("relay", state, ts), active=False)
    edges = [r for r in out if r["kind"] == "digital-edge"]
    chatter = [r for r in out if r["kind"] == "digital-chatter"]
    assert len(edges) == 5 and len(chatter) == 1     # 5 edges then one collapsed record
    assert chatter[0]["toggles"] > 5


def test_repeat_collapse_on_non_value_records():
    d, out = _disc()
    diag = lambda ts: {"kind": "diag", "subsystem": "daq", "level": "info", "message": "spam", "ts": ts}
    d.feed(diag(1.0), active=False)   # emitted
    d.feed(diag(1.1), active=False)   # identical → suppressed
    d.feed(diag(1.2), active=False)   # identical → suppressed
    d.feed({"kind": "diag", "subsystem": "daq", "level": "warning", "message": "other", "ts": 1.3},
           active=False)             # different → flush collapsed + emit
    collapsed = [r for r in out if r["kind"] == "repeat-collapsed"]
    assert len(collapsed) == 1 and collapsed[0]["count"] == 2
    assert d.suppressed == 2


def test_load_variable_meta_from_module_config():
    app = {"modules": [{"id": "variables", "config": {"variables": {
        "vbus": {"instance": "ps", "read": "measure", "range": {"min": 0, "max": 20}, "deadband": 0.5},
    }}}]}
    meta = load_variable_meta(app)
    assert meta["vbus"]["range"] == (0.0, 20.0) and meta["vbus"]["deadband"] == 0.5

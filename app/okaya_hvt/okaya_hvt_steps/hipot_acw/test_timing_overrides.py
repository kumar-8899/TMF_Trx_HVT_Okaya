"""hipot_acw timing overrides: the four relay/HV settle times come from an operator-editable global
file (<TMF_STATE_DIR>/config/hipot_timing.json, or OKAYA_HIPOT_TIMING_FILE for dev/tests) — one set
for all models, never in a recipe. Precedence: explicit recipe param > file > built-in default. A
missing/invalid file keeps the built-in defaults and never breaks a run."""

from __future__ import annotations

import json
import os

import pytest

from okaya_hvt_steps.hipot_acw.handler import HipotAcw, load_timing_overrides

_PARAMS = {"route": ["hipot_route_pri_sec"], "voltage": 1500.0, "test_time": 3.0,
           "max_current_ma": 5.0, "retries": 0}


class FakeCtx:
    """Minimal StepContext double: records waits and the interlock args, returns a clean pass."""

    def __init__(self):
        self.waited: list[float] = []
        self.interlock_args = None

    def write(self, name, value):
        return value

    def wait(self, seconds):
        self.waited.append(seconds)

    def invoke(self, action, method, args=None):
        if method == "open_all_verified":
            self.interlock_args = args
            return {"verified_open": True}
        if method == "last_acw_result":
            return "ARC"
        return (1.2, False)                 # measure_acw: leakage mA, no breakdown

    def diag(self, *a, **k):
        pass


def _write(tmp_path, d):
    p = tmp_path / "hipot_timing.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


# ---- the reader -----------------------------------------------------------------------------

def test_missing_file_yields_no_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(tmp_path / "nope.json"))
    assert load_timing_overrides() == {}


def test_reads_the_four_keys_and_ignores_extras(monkeypatch, tmp_path):
    p = _write(tmp_path, {"off_margin_s": 2, "settle_off_s": 1, "settle_s": 0.5,
                          "verify_settle_s": 0.15, "_comment": "hi", "junk": 9})
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(p))
    assert load_timing_overrides() == {"off_margin_s": 2.0, "settle_off_s": 1.0,
                                       "settle_s": 0.5, "verify_settle_s": 0.15}


def test_bad_json_is_ignored(monkeypatch, tmp_path):
    p = tmp_path / "hipot_timing.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(p))
    assert load_timing_overrides() == {}


def test_negative_and_nonnumeric_values_are_dropped(monkeypatch, tmp_path):
    p = _write(tmp_path, {"settle_s": -1, "settle_off_s": "x", "off_margin_s": 2.0})
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(p))
    assert load_timing_overrides() == {"off_margin_s": 2.0}


def test_an_edit_is_picked_up_on_the_next_read(monkeypatch, tmp_path):
    p = _write(tmp_path, {"settle_s": 0.5})
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(p))
    assert load_timing_overrides() == {"settle_s": 0.5}
    p.write_text(json.dumps({"settle_s": 0.9}), encoding="utf-8")
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 5))        # force a new mtime (same-second edits)
    assert load_timing_overrides() == {"settle_s": 0.9}


# ---- precedence in the handler --------------------------------------------------------------

def test_file_values_drive_the_settle_waits(monkeypatch, tmp_path):
    p = _write(tmp_path, {"off_margin_s": 2.0, "settle_off_s": 1.0, "settle_s": 0.5,
                          "verify_settle_s": 0.15})
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(p))
    ctx = FakeCtx()
    HipotAcw().execute(_PARAMS, ctx)
    assert ctx.waited[0] == 0.5                                     # settle_s (pre-test)
    assert ctx.waited[-1] == 1.0                                    # settle_off_s (post-open)
    assert ctx.waited[1] == pytest.approx(3.0 + 2.0, abs=0.1)       # test_time + off_margin_s
    assert ctx.interlock_args == [0.15, 2]                          # verify_settle_s + default retries


def test_built_in_defaults_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(tmp_path / "absent.json"))
    ctx = FakeCtx()
    HipotAcw().execute(_PARAMS, ctx)
    assert ctx.waited[0] == 1.0
    assert ctx.waited[-1] == 2.0
    assert ctx.waited[1] == pytest.approx(3.0 + 4.0, abs=0.1)
    assert ctx.interlock_args == [0.3, 2]


def test_an_explicit_recipe_param_still_wins_over_the_file(monkeypatch, tmp_path):
    p = _write(tmp_path, {"settle_s": 0.5})
    monkeypatch.setenv("OKAYA_HIPOT_TIMING_FILE", str(p))
    ctx = FakeCtx()
    HipotAcw().execute({**_PARAMS, "settle_s": 0.9}, ctx)
    assert ctx.waited[0] == 0.9

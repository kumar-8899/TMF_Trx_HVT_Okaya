"""D3 / X2 — calibration overlay (docs/contracts/CALIBRATION.md).

Overlay semantics, least-squares fit, effective-map baking, supervisor wiring, and the
cross-path guarantee: the controller's read and the backend engine's read of the SAME effective
map return the same scaled value, and a re-bake + reload needs no relaunch."""

import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

from core.services import calibration as cal
from core.services.controller_supervisor import ControllerSupervisor

BASE = {"signals": {
    "ai_v": {"instance": "daq", "read": "read_ai", "units": "V", "scale": {"gain": 2.0, "offset": 1.0}},
    "ao_v": {"instance": "daq", "write": "write_ao", "units": "V"},
}, "actions": {}}


# -- overlay semantics -------------------------------------------------------------------------

def test_overlay_replaces_scale_and_never_mutates_base():
    snap = copy.deepcopy(BASE["signals"])
    out = cal.overlay_calibration(BASE["signals"], {"signals": {"ai_v": {"gain": 3.0, "offset": -0.5}}})
    assert out["ai_v"]["scale"] == {"gain": 3.0, "offset": -0.5}      # overlay > map scale
    assert out["ai_v"]["calibrated"] is True
    assert BASE["signals"] == snap                                    # base untouched
    assert "calibrated" not in out["ao_v"]


def test_overlay_ignores_unknown_extra_and_invalid_entries():
    ov = {"signals": {
        "nope": {"gain": 2, "offset": 0},                              # unknown signal
        "ai_v": {"gain": 5.0, "offset": 0.0, "points": [1], "by": "x", "whatever": 1},  # extras ok
        "ao_v": {"gain": 0, "offset": 1},                              # gain 0 -> inverse scale would /0
    }}
    out = cal.overlay_calibration(BASE["signals"], ov)
    assert "nope" not in out
    assert out["ai_v"]["scale"] == {"gain": 5.0, "offset": 0.0}
    assert "scale" not in out["ao_v"]                                  # rejected, factory scale kept
    for bad in ({"gain": 2}, {"offset": 1}, {"gain": "x", "offset": 0}, {"gain": float("nan"), "offset": 0}):
        o = cal.overlay_calibration(BASE["signals"], {"signals": {"ai_v": bad}})
        assert o["ai_v"]["scale"] == BASE["signals"]["ai_v"]["scale"], bad


def test_overlay_none_is_identity():
    assert cal.overlay_calibration(BASE["signals"], None) == BASE["signals"]


# -- fit ---------------------------------------------------------------------------------------

def test_fit_recovers_gain_offset():
    pts = [{"raw": r, "reference": 2.0 * r + 0.5} for r in (0.0, 1.0, 4.0, 9.0)]
    f = cal.fit_linear(pts)
    assert f["gain"] == pytest.approx(2.0) and f["offset"] == pytest.approx(0.5)
    assert f["n"] == 4 and f["max_error"] == pytest.approx(0.0, abs=1e-9)


def test_fit_reports_residual_for_noisy_points():
    f = cal.fit_linear([{"raw": 0, "reference": 0}, {"raw": 5, "reference": 5.1}, {"raw": 10, "reference": 10}])
    assert 0 < f["max_error"] < 0.2


@pytest.mark.parametrize("pts", [
    [],
    [{"raw": 1, "reference": 1}],                                       # one point
    [{"raw": 1, "reference": 1}, {"raw": 1, "reference": 2}],           # same raw
    [{"raw": 1, "reference": 3}, {"raw": 2, "reference": 3}],           # flat reference -> gain 0
    [{"raw": 1, "reference": 1}, {"raw": "x", "reference": 2}],         # not a number
    [{"raw": 1, "reference": 1}, {"raw": float("inf"), "reference": 2}],
])
def test_fit_rejects_degenerate_points(pts):
    with pytest.raises(cal.CalibrationError):
        cal.fit_linear(pts)


# -- overlay file ------------------------------------------------------------------------------

def test_overlay_file_roundtrip_and_bad_file(tmp_path):
    p = tmp_path / "calibration" / "st1.json"
    assert cal.read_overlay(p) == {"schema_version": 1, "signals": {}}      # fresh bench
    ov = cal.set_signal(cal.read_overlay(p), "ai_v", {"gain": 2, "offset": 1, "n": 2, "max_error": 0.0},
                        points=[{"raw": 0, "reference": 1}], by="op")
    cal.write_overlay(p, ov)
    assert cal.read_overlay(p)["signals"]["ai_v"]["gain"] == 2
    assert not list(p.parent.glob("*.tmp"))                                  # atomic: no temp left
    assert cal.clear_signal(cal.read_overlay(p), "ai_v")["signals"] == {}
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(cal.CalibrationError):
        cal.read_overlay(p)


# -- bake --------------------------------------------------------------------------------------

def _ship(tmp_path) -> Path:
    p = tmp_path / "maps" / "st1.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(BASE), encoding="utf-8")
    return p


def test_bake_fresh_bench_is_identical_copy(tmp_path):
    ship = _ship(tmp_path)
    out = tmp_path / "data" / "controller.maps" / "st1.json"
    res = cal.bake_effective_map(ship, tmp_path / "data" / "calibration" / "st1.json", out)
    assert res == {"signals_calibrated": 0, "degraded": False}
    assert json.loads(out.read_text()) == BASE


def test_bake_applies_overlay_and_leaves_shipped_map_alone(tmp_path):
    ship, before = _ship(tmp_path), None
    before = ship.read_text()
    ovp = tmp_path / "data" / "calibration" / "st1.json"
    cal.write_overlay(ovp, {"signals": {"ai_v": {"gain": 4.0, "offset": 0.0}}})
    out = tmp_path / "data" / "controller.maps" / "st1.json"
    res = cal.bake_effective_map(ship, ovp, out)
    assert res["signals_calibrated"] == 1
    assert json.loads(out.read_text())["signals"]["ai_v"]["scale"] == {"gain": 4.0, "offset": 0.0}
    assert ship.read_text() == before


def test_bake_bad_overlay_degrades_loudly_to_shipped_scale(tmp_path):
    ship = _ship(tmp_path)
    ovp = tmp_path / "data" / "calibration" / "st1.json"
    ovp.parent.mkdir(parents=True)
    ovp.write_text("garbage", encoding="utf-8")
    logs = []
    out = tmp_path / "data" / "controller.maps" / "st1.json"
    res = cal.bake_effective_map(ship, ovp, out, log=lambda lvl, msg, **f: logs.append((lvl, msg, f)))
    assert res["degraded"] is True and json.loads(out.read_text()) == BASE
    assert logs and logs[0][0] == "error" and "overlay" in logs[0][1]


# -- supervisor --------------------------------------------------------------------------------

class _Diag:
    def __init__(self):
        self.rec = []

    def info(self, sub, msg, **k): self.rec.append(("info", msg, k))
    def warning(self, sub, msg, **k): self.rec.append(("warning", msg, k))
    def error(self, sub, msg, **k): self.rec.append(("error", msg, k))


def _sup(tmp_path, cfg_file):
    diag = _Diag()
    return ControllerSupervisor(stations=["st1"], broker_host="h", broker_port=1, diag=diag,
                                data_dir=tmp_path / "data", repo_root=tmp_path,
                                config_file=cfg_file, instruments=[]), diag


def _app_cfg(tmp_path):
    ship = _ship(tmp_path)
    cfgp = tmp_path / "controller.json"
    cfgp.write_text(json.dumps({"schema_version": 1, "stations": [
        {"station": "st1", "variable_map": "maps/st1.json"}]}), encoding="utf-8")
    return str(cfgp), ship


def test_supervisor_bakes_effective_map_and_points_controller_at_it(tmp_path):
    cfg_file, ship = _app_cfg(tmp_path)
    cal.write_overlay(cal.overlay_path(tmp_path / "data", "st1"),
                      {"signals": {"ai_v": {"gain": 9.0, "offset": 0.0}}})
    sup, diag = _sup(tmp_path, cfg_file)
    cfg = json.loads(sup._write_config().read_text())
    eff = Path(cfg["stations"][0]["variable_map"])
    assert eff == cal.effective_path(tmp_path / "data", "st1")
    assert json.loads(eff.read_text())["signals"]["ai_v"]["scale"]["gain"] == 9.0
    assert json.loads(ship.read_text()) == BASE                              # shipped never mutated
    idx = cal.read_index(tmp_path / "data")["st1"]
    assert idx["shipped"] == str(ship.resolve()) and idx["effective"] == str(eff)
    assert any(m == "calibration overlay applied" for _, m, _ in diag.rec)


def test_supervisor_fresh_bench_no_overlay_is_a_noop(tmp_path):
    cfg_file, _ = _app_cfg(tmp_path)
    sup, _ = _sup(tmp_path, cfg_file)
    cfg = json.loads(sup._write_config().read_text())
    assert json.loads(Path(cfg["stations"][0]["variable_map"]).read_text()) == BASE


def test_supervisor_bad_overlay_degrades_with_error_log(tmp_path):
    cfg_file, _ = _app_cfg(tmp_path)
    p = cal.overlay_path(tmp_path / "data", "st1")
    p.parent.mkdir(parents=True)
    p.write_text("{", encoding="utf-8")
    sup, diag = _sup(tmp_path, cfg_file)
    cfg = json.loads(sup._write_config().read_text())
    assert json.loads(Path(cfg["stations"][0]["variable_map"]).read_text()) == BASE
    assert any(lvl == "error" for lvl, _, _ in diag.rec)


def test_supervisor_missing_shipped_map_keeps_original_path(tmp_path):
    cfgp = tmp_path / "controller.json"
    cfgp.write_text(json.dumps({"schema_version": 1, "stations": [
        {"station": "st1", "variable_map": "maps/missing.json"}]}), encoding="utf-8")
    sup, diag = _sup(tmp_path, str(cfgp))
    cfg = json.loads(sup._write_config().read_text())
    assert cfg["stations"][0]["variable_map"].endswith("missing.json")       # controller reports it
    assert any(lvl == "warning" and "bake skipped" in m for lvl, m, _ in diag.rec)


# -- cross-path: controller read == backend read, and reload needs no relaunch -----------------

def _controller_pkg(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "controller"))
    for m in [m for m in sys.modules if m == "controller" or m.startswith("controller.")]:
        del sys.modules[m]
    from controller.instruments.variables import StationVariables
    from controller.loop import AsyncLoopThread
    return StationVariables, AsyncLoopThread


class _Inst:
    async def invoke(self, method, *args):
        return 3.0 if method == "read_ai" else None


def test_controller_and_backend_reads_agree_and_reload_needs_no_relaunch(tmp_path, monkeypatch):
    from modules.variables.engine import VariableEngine
    StationVariables, AsyncLoopThread = _controller_pkg(monkeypatch)
    ship = _ship(tmp_path)
    ovp, out = tmp_path / "ov.json", tmp_path / "eff.json"
    cal.bake_effective_map(ship, ovp, out)                                   # fresh bench

    class _Reg:
        def require(self, _): return _Inst()

    class _Inst2:
        def has(self, _): return True
        def require(self, _): return _Inst()

    loop = AsyncLoopThread()
    loop.start()
    try:
        ctl = StationVariables("st1", json.loads(out.read_text()), _Reg(), loop)
        eng = VariableEngine(_Inst2(), {"st1": json.loads(out.read_text())["signals"]},
                             diag=None, default_station="st1")
        assert ctl.read("ai_v")["value"] == asyncio.run(eng.read("ai_v"))["value"] == 3.0 * 2.0 + 1.0

        # apply a calibration: re-bake, then the controller reloads in place (NO new process)
        cal.write_overlay(ovp, {"signals": {"ai_v": {"gain": 10.0, "offset": 0.0}}})
        cal.bake_effective_map(ship, ovp, out)
        ctl.reload(json.loads(out.read_text()))
        eng.maps["st1"] = json.loads(out.read_text())["signals"]
        assert ctl.read("ai_v")["value"] == asyncio.run(eng.read("ai_v"))["value"] == 30.0
        # AO uses the inverse of the SAME overlay on both paths
        cal.write_overlay(ovp, {"signals": {"ao_v": {"gain": 2.0, "offset": 1.0}}})
        cal.bake_effective_map(ship, ovp, out)
        ctl.reload(json.loads(out.read_text()))
        assert ctl.write("ao_v", 5.0)["written"] == 5.0
    finally:
        loop.stop()

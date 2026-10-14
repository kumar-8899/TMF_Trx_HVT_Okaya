"""D3 / X2 — calibration service + routes (docs/contracts/CALIBRATION.md).

Python-controller mode bakes the effective map and asks the controller to reload; LabVIEW mode
applies the overlay to the backend engine only. Both paths are hot — no relaunch."""

import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.framework.contract import CoreServices
from core.services import calibration as cal
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from instrumentlib import InstrumentBase, IPowerSource, instrument_library
from modules.variables.calibration import CalibrationUnavailable
from modules.variables.variants.default import DefaultVariables


@instrument_library(
    library_id="cal_supply", vendor="T", model="PS", capabilities=["power_source"],
    interface_version=1, transports=["sim"], library_version="1.0.0",
    generated_by="test", manual_reference="none",
)
class CalSupply(InstrumentBase, IPowerSource):
    async def measure_current(self):
        return float(await self.transport.query("MEAS:CURR?"))        # sim -> 1.0

    async def set_voltage(self, volts):
        await self.transport.write(f"VOLT {volts}")


class FakeBridge:
    online = True
    station = "st1"

    def __init__(self):
        self.requests: list = []
        self.replies: dict = {}

    def serve(self, op, handler):
        pass

    async def request(self, op, args, *, station, timeout=None):
        self.requests.append((op, args, station))
        r = self.replies.get(op, {"ok": True, "result": {}})
        if isinstance(r, Exception):
            raise r
        return r


def _cfg(tmp_path):
    return {
        "data_dir": str(tmp_path / "data"),
        "instances": [{"id": "psu", "library": "cal_supply", "simulated": True}],
        "variables": {
            "ai_i": {"instance": "psu", "read": "measure_current", "units": "A",
                     "scale": {"gain": 2.0, "offset": 1.0}},
            "ao_v": {"instance": "psu", "write": "set_voltage", "units": "V"},
            "dig": {"instance": "psu", "read": "measure_current", "calibratable": False},
        },
    }


async def _mod(tmp_path, kind):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    bridge = FakeBridge()
    diags = []
    core = CoreServices(db=db, bridge=bridge, controller_kind=kind, station="st1",
                        diag=Diagnostics("st1", "0.0.0", sinks=[diags.append]))
    m = DefaultVariables.construct(core, _cfg(tmp_path))
    await m.start()
    return m, bridge, db, diags


@pytest.fixture
async def lv(tmp_path):                       # labview: backend engine is the only read path
    m, b, db, diags = await _mod(tmp_path, "labview")
    yield m, b, tmp_path
    await m.stop()
    await db.close()


PTS = [{"raw": 0.0, "reference": 0.5}, {"raw": 10.0, "reference": 20.5}]       # gain 2, offset 0.5


async def test_list_hides_non_calibratable_and_shows_factory_scale(lv):
    m, _, _ = lv
    rows = {r["name"]: r for r in m.calibration.list_signals(None)}
    assert set(rows) == {"ai_i", "ao_v"}                       # `calibratable: false` hidden
    assert rows["ai_i"]["factory"] == {"gain": 2.0, "offset": 1.0}
    assert rows["ai_i"]["readable"] and not rows["ai_i"]["writable"]
    assert rows["ao_v"]["writable"] and rows["ao_v"]["calibration"] is None


async def test_apply_changes_engine_read_immediately_and_persists(lv):
    m, _, tmp = lv
    assert (await m.engine.read("ai_i"))["value"] == 3.0                 # 1*2+1 factory
    res = await m.calibration.apply("ai_i", PTS, None, "alice")
    assert res["gain"] == pytest.approx(2.0) and res["offset"] == pytest.approx(0.5)
    assert res["controller"] == "not-applicable"
    r = await m.engine.read("ai_i")
    assert r["value"] == pytest.approx(2.5) and r["raw"] == 1.0         # 1*2+0.5; raw untouched
    saved = cal.read_overlay(cal.overlay_path(tmp / "data", "st1"))["signals"]["ai_i"]
    assert saved["by"] == "alice" and saved["points"] == PTS            # audit trail kept
    assert m.calibration.list_signals(None)[0]["calibration"]["gain"] == pytest.approx(2.0)


async def test_overlay_survives_restart_via_load_overlays(lv):
    m, _, tmp = lv
    await m.calibration.apply("ai_i", PTS, None, "a")
    m.engine.set_overlay("st1", {})                                      # simulate a fresh process
    assert (await m.engine.read("ai_i"))["value"] == 3.0
    m.calibration.load_overlays()
    assert (await m.engine.read("ai_i"))["value"] == pytest.approx(2.5)


async def test_bad_overlay_at_start_is_loud_and_factory_scale_kept(tmp_path):
    p = cal.overlay_path(tmp_path / "data", "st1")
    p.parent.mkdir(parents=True)
    p.write_text("{broken", encoding="utf-8")
    m, _, db, diags = await _mod(tmp_path, "labview")
    try:
        assert (await m.engine.read("ai_i"))["value"] == 3.0
        assert any(e.get("level") == "error" and "overlay ignored" in e.get("message", "")
                   for e in map(lambda e: e if isinstance(e, dict) else e.__dict__, diags))
    finally:
        await m.stop()
        await db.close()


async def test_reset_returns_to_factory(lv):
    m, _, _ = lv
    await m.calibration.apply("ai_i", PTS, None, "a")
    await m.calibration.reset("ai_i", None, "a")
    assert (await m.engine.read("ai_i"))["value"] == 3.0
    assert m.calibration.list_signals(None)[0]["calibration"] is None


async def test_output_write_uses_inverse_of_overlay(lv):
    m, _, _ = lv
    await m.calibration.apply("ao_v", [{"raw": 0, "reference": 1.0}, {"raw": 10, "reference": 21.0}],
                              None, "a")                                 # v = 2*raw + 1
    await m.engine.write("ao_v", 5.0)
    assert "VOLT 2.0" in m.instances.get("psu").transport.writes          # raw = (5-1)/2


async def test_drive_raw_commands_exact_raw_through_current_scale(lv):
    m, _, _ = lv
    await m.calibration.apply("ao_v", [{"raw": 0, "reference": 1.0}, {"raw": 10, "reference": 21.0}],
                              None, "a")
    r = await m.calibration.drive_raw("ao_v", 4.0, None)
    assert r["commanded"] == pytest.approx(9.0)                           # 4*2+1
    assert "VOLT 4.0" in m.instances.get("psu").transport.writes          # instrument got raw 4


async def test_unknown_signal_and_degenerate_fit(lv):
    m, _, _ = lv
    with pytest.raises(KeyError):
        await m.calibration.apply("nope", PTS, None, "a")
    with pytest.raises(cal.CalibrationError):
        await m.calibration.apply("ai_i", [{"raw": 1, "reference": 1}], None, "a")
    assert not cal.overlay_path(lv[2] / "data", "st1").exists()           # nothing written on reject


# -- python controller mode -------------------------------------------------------------------

@pytest.fixture
async def py(tmp_path):
    ship = tmp_path / "maps" / "st1.json"
    ship.parent.mkdir(parents=True)
    ship.write_text(json.dumps({"signals": {
        "ai_shipped": {"instance": "psu", "read": "measure_current",
                       "scale": {"gain": 1.0, "offset": 0.0}}}, "actions": {}}), encoding="utf-8")
    d = tmp_path / "data"
    cal.write_index(d, {"st1": {"shipped": str(ship), "effective": str(cal.effective_path(d, "st1")),
                                "overlay": str(cal.overlay_path(d, "st1"))}})
    m, b, db, _ = await _mod(tmp_path, "python")
    yield m, b, d
    await m.stop()
    await db.close()


async def test_python_mode_lists_shipped_map_signals_too(py):
    m, _, _ = py
    assert "ai_shipped" in {r["name"] for r in m.calibration.list_signals(None)}


async def test_python_apply_bakes_effective_map_and_reloads_controller(py):
    m, b, d = py
    res = await m.calibration.apply("ai_shipped", PTS, None, "a")
    assert res["controller"] == "reloaded"
    assert ("calibration.reload", {}, "st1") in b.requests
    eff = json.loads(cal.effective_path(d, "st1").read_text())
    assert eff["signals"]["ai_shipped"]["scale"]["gain"] == pytest.approx(2.0)
    assert eff["signals"]["ai_shipped"]["calibrated"] is True


async def test_python_apply_controller_busy_saves_and_reports_pending(py):
    m, b, d = py
    b.replies["calibration.reload"] = {"ok": False, "error": {"code": "Busy", "message": "st1 is running"}}
    res = await m.calibration.apply("ai_shipped", PTS, None, "a")
    assert res["controller"] == "pending" and "running" in res["detail"]
    assert cal.read_overlay(cal.overlay_path(d, "st1"))["signals"]["ai_shipped"]   # saved anyway


async def test_python_apply_bridge_down_saves_and_reports_pending(py):
    m, b, d = py
    b.replies["calibration.reload"] = RuntimeError("offline")
    res = await m.calibration.apply("ai_shipped", PTS, None, "a")
    assert res["controller"] == "pending"


async def test_python_read_raw_goes_through_the_controller(py):
    m, b, _ = py
    b.replies["variable.read"] = {"ok": True, "result": {"name": "ai_shipped", "value": 7.0,
                                                          "raw": 3.5, "units": "A"}}
    r = await m.calibration.read_raw("ai_shipped", None)
    assert r["raw"] == 3.5 and r["scaled"] == 7.0
    assert b.requests[-1][0] == "variable.read"
    b.replies["variable.read"] = {"ok": False, "error": {"message": "instrument offline"}}
    with pytest.raises(CalibrationUnavailable, match="offline"):
        await m.calibration.read_raw("ai_shipped", None)


# -- routes: MAINTENANCE.CALIBRATE gate -------------------------------------------------------

def _client(m):
    tv = TokenVerifier()
    table = {"cal": Principal("carol", role="maintenance", permissions=frozenset({"MAINTENANCE.CALIBRATE"})),
             "op": Principal("oscar", role="operator",
                             permissions=frozenset({"TEST.RUN", "CONFIG.VIEW", "HEALTH.MAINTENANCE"}))}

    def verify(t):
        if t not in table:
            raise AuthError("bad")
        return table[t]

    tv.register(verify)
    app = FastAPI()
    app.state.auth = tv
    app.include_router(m.router)
    return TestClient(app)


async def test_routes_are_gated_on_maintenance_calibrate(lv):
    m, _, _ = lv
    c = _client(m)
    for method, url, body in [("get", "/calibration/signals", None),
                              ("post", "/calibration/fit", {"points": PTS}),
                              ("post", "/calibration/ai_i/raw", {}),
                              ("post", "/calibration/ao_v/drive", {"raw": 1}),
                              ("post", "/calibration/ai_i/apply", {"points": PTS}),
                              ("delete", "/calibration/ai_i", None)]:
        kw = {"json": body} if body is not None else {}
        assert getattr(c, method)(url, headers={"Authorization": "Bearer op"}, **kw).status_code == 403, url
        assert getattr(c, method)(url, **kw).status_code == 401, url


async def test_routes_apply_fit_and_errors(lv):
    m, _, _ = lv
    c = _client(m)
    h = {"Authorization": "Bearer cal"}
    assert c.post("/calibration/fit", headers=h, json={"points": PTS}).json()["gain"] == pytest.approx(2.0)
    assert c.post("/calibration/fit", headers=h, json={"points": PTS[:1]}).status_code == 422
    assert c.post("/calibration/nope/apply", headers=h, json={"points": PTS}).status_code == 404
    ok = c.post("/calibration/ai_i/apply", headers=h, json={"points": PTS})
    assert ok.status_code == 200 and ok.json()["controller"] == "not-applicable"
    assert c.get("/calibration/signals", headers=h).json()[0]["calibration"]["gain"] == pytest.approx(2.0)
    assert c.delete("/calibration/ai_i", headers=h).status_code == 200
    assert c.post("/calibration/ao_v/drive", headers=h, json={}).status_code == 422

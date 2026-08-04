"""M3 — /readyz per-station link body. M4 — runs per-station active-run gate +
required station (MULTI_STATION.md §3, §4.1, §9 slices M3-M4)."""

import json

import httpx
import pytest
from httpx import ASGITransport

from core.app import create_app
from core.framework.contract import CoreServices
from core.services.config import DEFAULT_CONFIG_DIR
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.runs.errors import RunActiveError, RunError
from modules.runs.variants.default import DefaultRuns


# ---- M3: /readyz per-station body -----------------------------------------

def _seed(config_dir, stations):
    lic = json.loads((DEFAULT_CONFIG_DIR / "license.example.json").read_text())
    lic["entitlements"]["limits"]["max_stations"] = 8
    lic["entitlements"]["modules"] = {"hello": True}
    (config_dir / "license.json").write_text(json.dumps(lic), encoding="utf-8")
    (config_dir / "app.json").write_text(json.dumps(
        {"schema_version": 1, "stations": stations, "license": "config/license.json",
         "modules": [{"id": "hello", "variant": "default"}]}), encoding="utf-8")


async def test_readyz_reports_every_station(config_dir):
    _seed(config_dir, ["st1", "st2", "st3"])
    app = create_app(config_dir=config_dir, db_path=":memory:", enable_bridge=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            body = (await c.get("/readyz")).json()
            assert set(body["stations"]) == {"st1", "st2", "st3"}
            # bridge disabled -> every link offline, but the body still enumerates them
            assert all(v == "offline" for v in body["stations"].values())


# ---- M4: runs per-station active gate --------------------------------------

class _Bridge:
    def __init__(self):
        self.requests = []

    async def request(self, op, args, *, station=None, timeout=None):
        self.requests.append((op, station))
        return {"run_id": args.get("run_id"), "accepted": True}


@pytest.fixture
async def runs():
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, bridge=_Bridge(),
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]),
                        stations=["st1", "st2"], station="st1")
    yield DefaultRuns.construct(core, {})
    await db.close()


async def test_start_marks_station_active_and_records_station(runs):
    out = await runs.run_start({"recipe_id": "demo", "station": "st1"})
    assert out["station"] == "st1"
    run = await runs.get_run(out["run_id"])
    assert run["data"]["station"] == "st1"


async def test_second_run_on_same_station_refused(runs):
    await runs.run_start({"recipe_id": "demo", "station": "st1"})
    with pytest.raises(RunActiveError):
        await runs.run_start({"recipe_id": "demo", "station": "st1"})


async def test_other_station_unaffected(runs):
    await runs.run_start({"recipe_id": "demo", "station": "st1"})
    out2 = await runs.run_start({"recipe_id": "demo", "station": "st2"})   # independent socket
    assert out2["station"] == "st2"


async def test_terminal_event_frees_the_station(runs):
    out = await runs.run_start({"recipe_id": "demo", "station": "st1"})
    await runs._on_event(f"tmf/st1/event/run-finished",
                         {"type": "run-finished", "ts": 1.0,
                          "payload": {"run_id": out["run_id"], "result": "PASS"}})
    # st1 free again
    out2 = await runs.run_start({"recipe_id": "demo", "station": "st1"})
    assert out2["run_id"] != out["run_id"]


async def test_station_required_when_multi(runs):
    with pytest.raises(RunError):
        await runs.run_start({"recipe_id": "demo"})          # no station, 2 sockets


async def test_unknown_station_rejected(runs):
    with pytest.raises(RunError):
        await runs.run_start({"recipe_id": "demo", "station": "st9"})


async def test_failed_start_releases_reservation(runs):
    # a bridge that raises -> the station must not stay stuck active
    class _Boom:
        async def request(self, *a, **k):
            raise RuntimeError("bridge down")
    runs.core.bridge = _Boom()
    with pytest.raises(RuntimeError):
        await runs.run_start({"recipe_id": "demo", "station": "st1"})
    runs.core.bridge = _Bridge()
    out = await runs.run_start({"recipe_id": "demo", "station": "st1"})   # not stuck
    assert out["station"] == "st1"

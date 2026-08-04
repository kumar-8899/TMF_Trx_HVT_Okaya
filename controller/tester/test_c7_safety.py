"""C7 — safety: monitors-as-data, blast-radius resolution, the reflex fan-out, faulted
resources, and the teardown-skipped trip path (PYTHON_CONTROLLER.md §10, §5.5).

Proves the slice invariant: a trip on one station leaves the others running."""

import asyncio
import time

import pytest

import controller.step_types  # noqa: F401
from controller.instruments.variables import StationVariables, VariableError
from controller.runstate import FAULTED, IDLE, RUNNING, RunEngine
from controller.safety import (Monitor, SafetyConfigError, SafetyController, SafetyMap,
                              parse_monitors)


# ---- monitors are data (§10.1) -------------------------------------------

def test_parse_monitors_valid():
    ms = parse_monitors([
        {"id": "estop", "scope": "pc"},
        {"id": "ovp", "scope": "station", "station": "st2"},
        {"id": "temp", "scope": "resource", "resource": "chamber_1"},
    ])
    assert [m.id for m in ms] == ["estop", "ovp", "temp"]
    assert ms[1].station == "st2" and ms[2].resource == "chamber_1"


@pytest.mark.parametrize("bad", [
    [{"scope": "pc"}],                                   # missing id
    [{"id": "a", "scope": "pc"}, {"id": "a", "scope": "pc"}],  # duplicate
    [{"id": "a", "scope": "cell"}],                      # bad scope
    [{"id": "a", "scope": "station"}],                   # station scope needs station
    [{"id": "a", "scope": "resource"}],                  # resource scope needs resource
])
def test_parse_monitors_rejects(bad):
    with pytest.raises(SafetyConfigError):
        parse_monitors(bad)


# ---- blast radius (§10.2) -------------------------------------------------

_ALL = ["st1", "st2", "st3"]
_INST = {"psu_st1": ["st1"], "psu_st2": ["st2"], "chamber": ["st2", "st3"], "shared_all": _ALL}


def _map(monitors):
    return SafetyMap(monitors, _ALL, _INST)


def test_pc_scope_hits_every_station_and_instrument():
    r = _map([Monitor("estop", "pc")]).radius("estop")
    assert set(r.stations) == set(_ALL)
    assert set(r.instances) == set(_INST)                       # everything on the PC


def test_station_scope_only_that_station_and_its_exclusive_instruments():
    r = _map([Monitor("ovp", "station", station="st1")]).radius("ovp")
    assert r.stations == ["st1"]
    assert r.instances == ["psu_st1"]          # NOT shared_all (serves all) — §9.3 keeps it read-only


def test_resource_scope_hits_the_resource_and_the_stations_using_it():
    r = _map([Monitor("temp", "resource", resource="chamber")]).radius("temp")
    assert set(r.stations) == {"st2", "st3"}                    # from the static map, not who holds it
    assert r.instances == ["chamber"]


def test_map_rejects_unknown_references():
    with pytest.raises(SafetyConfigError):
        _map([Monitor("x", "station", station="st9")])
    with pytest.raises(SafetyConfigError):
        _map([Monitor("x", "resource", resource="nope")])


# ---- fakes for the reflex fan-out ----------------------------------------

class FakeInst:
    def __init__(self, iid):
        self.instance_id = iid
        self.disabled = 0

    async def emergency_disable(self):
        self.disabled += 1


class FakeRegistry:
    def __init__(self, insts):
        self._by = {i.instance_id: i for i in insts}
        self._faulted: set[str] = set()

    def get(self, iid):
        return self._by.get(iid)

    def require(self, iid):
        return self._by[iid]

    async def emergency_disable(self, instances):
        for i in instances:
            await i.emergency_disable()

    def mark_faulted(self, ids):
        self._faulted.update(ids)

    def clear_faulted(self, ids=None):
        self._faulted.clear() if ids is None else self._faulted.difference_update(ids)

    def is_faulted(self, iid):
        return iid in self._faulted

    def faulted(self):
        return sorted(self._faulted)


class FakeLoop:
    def run(self, coro, *, timeout=None):
        return asyncio.new_event_loop().run_until_complete(coro)


class _Vars:
    state = None
    def read(self, name): return {"value": 5.0}
    def write(self, name, value): return {"written": value}


def _engine(station, recipe, tore):
    events = []
    eng = RunEngine(station, variables=_Vars(), emit=lambda t, p: events.append((t, p)),
                    recipe_fetch=lambda rid, ver: recipe, safe_state=lambda: tore.append(station),
                    diag=lambda *a, **k: None)
    return eng, events


def _controller(smap, insts, engines, published):
    reg = FakeRegistry(insts)
    ctrl = SafetyController(smap, reg, FakeLoop(), engines,
                           (lambda st, sub, p: published.append((st, sub, p))))
    return ctrl, reg


# ---- the fan-out, in §10.3 order ------------------------------------------

def test_trip_disables_faults_and_emits_in_order():
    insts = [FakeInst("psu_st1")]
    smap = SafetyMap([Monitor("ovp", "station", station="st1")], ["st1", "st2"],
                     {"psu_st1": ["st1"], "psu_st2": ["st2"]})
    tore1, tore2 = [], []
    e1, ev1 = _engine("st1", {"steps": [{"type": "wait", "id": "w", "params": {"seconds": 3}}]}, tore1)
    e2, ev2 = _engine("st2", {"steps": [{"type": "wait", "id": "w", "params": {"seconds": 3}}]}, tore2)
    published = []
    ctrl, reg = _controller(smap, insts, {"st1": e1, "st2": e2}, published)

    e1.start({"recipe_id": "r", "run_id": "r1"})
    e2.start({"recipe_id": "r", "run_id": "r2"})
    time.sleep(0.1)
    assert e1.state == RUNNING and e2.state == RUNNING

    ctrl.handle_trip("ovp")                        # synchronous fan-out
    e1._thread.join(5)

    # 1. output cut  2. resource faulted
    assert insts[0].disabled == 1
    assert reg.is_faulted("psu_st1")
    # 3. safety-trip published on the affected station, no run_id
    trips = [p for st, sub, p in published if sub == "event/safety-trip"]
    assert trips and trips[0]["payload"]["monitor_id"] == "ovp"
    assert "run_id" not in trips[0]["payload"] and "run_id" not in trips[0]
    # 4. affected station faulted, teardown SKIPPED; run-aborted reason safety:<id>
    assert e1.state == FAULTED and tore1 == []
    aborted = [p for t, p in ev1 if t == "run-aborted"]
    assert aborted and aborted[0]["reason"] == "safety:ovp"

    # the invariant: st2 untouched, still running
    assert e2.state == RUNNING and tore2 == []
    e2.abort(); e2._thread.join(5)


def test_idle_station_in_radius_still_faults():
    smap = _map([Monitor("estop", "pc")])
    e1, _ = _engine("st1", {"steps": []}, [])
    ctrl, reg = _controller(smap, [FakeInst(i) for i in _INST], {"st1": e1}, [])
    ctrl.handle_trip("estop")
    assert e1.state == FAULTED                     # never started, but won't start into a trip


def test_run_start_refused_while_faulted():
    smap = _map([Monitor("estop", "pc")])
    e1, _ = _engine("st1", {"steps": []}, [])
    ctrl, _ = _controller(smap, [FakeInst(i) for i in _INST], {"st1": e1}, [])
    ctrl.handle_trip("estop")
    r = e1.start({"recipe_id": "r"})
    assert r["accepted"] is False and r["error"] == "station_faulted"


# ---- faulted resource fails fast (§10.3 step 4) --------------------------

def test_faulted_instance_read_fails_fast():
    reg = FakeRegistry([FakeInst("psu_st1")])
    reg.mark_faulted(["psu_st1"])
    v = StationVariables("st1", {"signals": {"v": {"instance": "psu_st1", "read": "measure_voltage"}}},
                         reg, FakeLoop())
    with pytest.raises(VariableError, match="faulted"):
        v.read("v")


# ---- fault clearing (§10.4, minimal mechanism) ---------------------------

def test_clear_unfaults_resources_and_stations():
    smap = _map([Monitor("estop", "pc")])
    e1, _ = _engine("st1", {"steps": []}, [])
    ctrl, reg = _controller(smap, [FakeInst(i) for i in _INST], {"st1": e1}, [])
    ctrl.handle_trip("estop")
    assert reg.faulted() and e1.state == FAULTED

    out = ctrl.clear("estop")
    assert out["ok"] and "st1" in out["cleared_stations"]
    assert reg.faulted() == [] and e1.state == IDLE


# ---- reflex thread: trip() enqueues, the thread does the work -------------

def test_reflex_thread_processes_enqueued_trip():
    smap = _map([Monitor("estop", "pc")])
    e1, _ = _engine("st1", {"steps": []}, [])
    ctrl, reg = _controller(smap, [FakeInst(i) for i in _INST], {"st1": e1}, [])
    ctrl.start()
    try:
        assert ctrl.trip("estop")["accepted"] is True
        deadline = time.time() + 3
        while time.time() < deadline and e1.state != FAULTED:
            time.sleep(0.02)
        assert e1.state == FAULTED and reg.faulted()
        assert ctrl.trip("nope")["ok"] is False        # unknown monitor rejected
    finally:
        ctrl.stop()

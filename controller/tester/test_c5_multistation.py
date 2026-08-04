"""C5 — multi-station: the shared-instrument no-lease rule, per-station teardown
targeting, and independent per-station run state machines (PYTHON_CONTROLLER.md §9.3,
§2.1, MULTI_STATION.md §4.1)."""

import time

import controller.step_types  # noqa: F401
from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import check_no_lease
from controller.runstate import IDLE, RUNNING, RunEngine
from tester import _fakelib


# ---- §9.3 shared-instrument no-lease rule ---------------------------------

_STATIONS = {"psu_st1": ["st1"], "psu_st2": ["st2"], "daq_shared": ["st1", "st2"]}


def test_shared_write_refused():
    maps = {"st1": {"signals": {"v": {"instance": "daq_shared", "write": "set_voltage"}}}}
    errs = check_no_lease(_STATIONS, maps)
    assert errs and "daq_shared" in errs[0] and "write" in errs[0]


def test_shared_read_only_allowed():
    maps = {"st1": {"signals": {"v": {"instance": "daq_shared", "read": "read_voltage"}}}}
    assert check_no_lease(_STATIONS, maps) == []


def test_station_private_write_allowed():
    maps = {"st1": {"signals": {"v": {"instance": "psu_st1", "write": "set_voltage"}}}}
    assert check_no_lease(_STATIONS, maps) == []


def test_shared_action_refused():
    maps = {"st1": {"actions": {"mux": {"instance": "daq_shared", "capability": "multiplexer"}}}}
    errs = check_no_lease(_STATIONS, maps)
    assert errs and "action" in errs[0]


# ---- per-station teardown targeting ---------------------------------------

def test_instances_for_station_filters():
    reg = InstrumentRegistry(loop=None)
    lib = _fakelib.ensure_registered()
    reg.build([
        {"id": "psu_st1", "library": lib, "simulated": True, "params": {"resource": "a"}, "stations": ["st1"]},
        {"id": "psu_st2", "library": lib, "simulated": True, "params": {"resource": "b"}, "stations": ["st2"]},
        {"id": "daq", "library": lib, "simulated": True, "params": {"resource": "c"}, "stations": ["st1", "st2"]},
    ])
    st1 = {i.instance_id for i in reg.instances_for_station("st1")}
    st2 = {i.instance_id for i in reg.instances_for_station("st2")}
    assert st1 == {"psu_st1", "daq"}         # st2's private PSU is NOT torn down with st1
    assert st2 == {"psu_st2", "daq"}


# ---- independent run state machines ---------------------------------------

class _Vars:
    def read(self, name): return {"value": 5.0}
    def write(self, name, value): return {"written": value}


def _engine(station, recipe, tore):
    events = []
    eng = RunEngine(station, variables=_Vars(), emit=lambda t, p: events.append((t, p)),
                    recipe_fetch=lambda rid, ver: recipe, safe_state=lambda: tore.append(station),
                    diag=lambda *a, **k: None)
    return eng, events


def test_two_stations_run_independently():
    tore: list[str] = []
    # st1: a long wait (abortable); st2: a quick measure that passes
    e1, ev1 = _engine("st1", {"steps": [{"type": "wait", "id": "w", "params": {"seconds": 3}}]}, tore)
    e2, ev2 = _engine("st2", {"steps": [{"type": "measure_and_compare", "id": "m",
                                         "params": {"signal": "v", "min": 0, "max": 10}}]}, tore)
    e1.start({"recipe_id": "long", "run_id": "r1"})
    e2.start({"recipe_id": "quick", "run_id": "r2"})
    time.sleep(0.15)
    assert e1.state == RUNNING          # st1 still running
    e1.abort()                          # abort ONLY st1
    e1._thread.join(5)
    e2._thread.join(5)

    t1 = [t for t, _ in ev1 if t in ("run-finished", "run-aborted")]
    t2 = [t for t, _ in ev2 if t in ("run-finished", "run-aborted")]
    assert t1 == ["run-aborted"] and e1.state == IDLE     # st1 aborted + torn down
    assert t2 == ["run-finished"]                          # st2 finished, untouched by st1's abort
    assert ev2[-1][1]["result"] == "PASS"
    assert "st1" in tore and "st2" in tore                 # each ran its OWN teardown

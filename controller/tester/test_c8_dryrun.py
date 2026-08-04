"""C8 — dry run (PYTHON_CONTROLLER.md §12.2): walk the whole tree, resolve every signal +
action name against the station map, no hardware, no handler body — DRY_RUN_PASS/FAIL."""

import controller.step_types  # noqa: F401
from controller.dryrun import dry_run
from controller.runstate import IDLE, RunEngine


class _Vars:
    """Only the map surface dry-run needs — no instrument, no loop (proves no hardware)."""
    def __init__(self, signals=(), actions=()):
        self.signals = {s: {} for s in signals}
        self.actions = {a: {} for a in actions}

    def read(self, name):  # would blow up if a handler ran — it must not
        raise AssertionError("dry run must not read hardware")

    def write(self, name, value):
        raise AssertionError("dry run must not write hardware")


_RECIPE = {"steps": [
    {"type": "set_output", "id": "s1", "params": {"signal": "vout", "value": 5}},
    {"type": "sweep", "id": "sw", "params": {"signal": "vout", "values": [1, 2], "steps": [
        {"type": "measure_and_compare", "id": "m", "params": {"signal": "iout", "min": 0, "max": 1}},
    ]}},
]}


def test_dry_run_pass_when_every_name_resolves():
    result, errors = dry_run(_RECIPE, _Vars(signals=["vout", "iout"]))
    assert result == "DRY_RUN_PASS" and errors == []


def test_dry_run_reports_missing_signal_deep_in_the_tree():
    result, errors = dry_run(_RECIPE, _Vars(signals=["vout"]))   # iout missing, inside the sweep
    assert result == "DRY_RUN_FAIL"
    assert any("iout" in e and "m" in e for e in errors)


def test_dry_run_flags_unknown_step_type():
    recipe = {"steps": [{"type": "frobnicate", "id": "x", "params": {}}]}
    result, errors = dry_run(recipe, _Vars())
    assert result == "DRY_RUN_FAIL" and any("unknown step type" in e for e in errors)


def test_dry_run_collects_all_errors_not_just_first():
    recipe = {"steps": [
        {"type": "set_output", "id": "a", "params": {"signal": "nope1", "value": 1}},
        {"type": "measure_and_compare", "id": "b", "params": {"signal": "nope2", "min": 0}},
    ]}
    _, errors = dry_run(recipe, _Vars())
    assert len(errors) == 2                                       # surfaces every gap in one pass


def test_dry_run_resolves_composite_condition_signals():
    recipe = {"steps": [{"type": "if", "id": "g", "params": {
        "condition": {"signal": "enable", "equals": 1}, "steps": []}}]}
    assert dry_run(recipe, _Vars(signals=["enable"]))[0] == "DRY_RUN_PASS"
    assert dry_run(recipe, _Vars())[0] == "DRY_RUN_FAIL"


# ---- through the run engine (§12.2 emits run-finished DRY_RUN_*) -----------

def _engine(vars_, recipe):
    events = []
    eng = RunEngine("st1", variables=vars_, emit=lambda t, p: events.append((t, p)),
                    recipe_fetch=lambda rid, ver: recipe, safe_state=lambda: None,
                    diag=lambda *a, **k: None)
    return eng, events


def test_engine_dry_run_emits_started_then_dry_run_pass():
    eng, events = _engine(_Vars(signals=["vout", "iout"]), _RECIPE)
    eng.start({"recipe_id": "r", "run_id": "d1", "dry_run": True})
    eng._thread.join(5)
    types = [t for t, _ in events]
    assert types == ["run-started", "run-finished"]              # zero step events
    assert events[0][1]["dry_run"] is True
    assert events[-1][1]["result"] == "DRY_RUN_PASS" and events[-1][1]["errors"] == []
    assert eng.state == IDLE                                     # dry run leaves the station idle


def test_engine_dry_run_fail_lists_errors():
    eng, events = _engine(_Vars(signals=["vout"]), _RECIPE)
    eng.start({"recipe_id": "r", "run_id": "d2", "dry_run": True})
    eng._thread.join(5)
    fin = events[-1][1]
    assert fin["result"] == "DRY_RUN_FAIL" and fin["errors"]

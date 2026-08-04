"""C10 — app step-type packages (PYTHON_CONTROLLER.md §7.5, §16). Loading a package registers
its step types with no framework change; the CI gate rejects a non-conforming/schemaless one;
and a recipe using an app step type dry-run-validates against the station map."""

import os

import controller.step_types  # noqa: F401 — core types
from controller import registry
from controller.dryrun import dry_run
from controller.packages import load_step_type_packages, validate_app_step_types
from controller.registry import STEP_REGISTRY, register_step_type

_EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")


class _Vars:
    def __init__(self, signals=()):
        self.signals = {s: {} for s in signals}
        self.actions = {}


def test_loading_a_package_registers_its_step_types():
    load_step_type_packages([_EXAMPLES], ["demo_steps"])
    st = registry.get("relay_cycle")
    assert st is not None and st.kind == "application"        # shipped without a framework release
    assert st.required_signals == ("relay_coil", "relay_feedback")


def test_ci_gate_passes_for_the_example_package():
    load_step_type_packages([_EXAMPLES], ["demo_steps"])
    gate = validate_app_step_types()
    assert all(not g.startswith("relay_cycle:") for g in gate), gate


def test_ci_gate_rejects_nonconforming_app_step_type():
    @register_step_type(type_id="_bad_demo_c10", kind="application")   # note: no schema_path
    class Bad:
        def execute(self, params, ctx):
            import socket                     # rule2: forbidden import
            import time
            socket.socket()
            time.sleep(1)                     # rule1: bare sleep
            return None
    try:
        gate = [g for g in validate_app_step_types() if g.startswith("_bad_demo_c10:")]
        assert any("rule1" in g for g in gate)
        assert any("rule2" in g for g in gate)
        assert any("no schema_path" in g for g in gate)
    finally:
        STEP_REGISTRY.pop("_bad_demo_c10", None)


def test_recipe_using_app_step_type_dry_run_validates():
    load_step_type_packages([_EXAMPLES], ["demo_steps"])
    recipe = {"steps": [{"type": "relay_cycle", "id": "rc", "params": {
        "cycles": 2, "on_value": 1, "off_value": 0, "fb_min": 0.5, "fb_max": 1.5}}]}
    assert dry_run(recipe, _Vars(["relay_coil", "relay_feedback"]))[0] == "DRY_RUN_PASS"
    result, errors = dry_run(recipe, _Vars(["relay_coil"]))          # feedback missing
    assert result == "DRY_RUN_FAIL" and any("relay_feedback" in e for e in errors)

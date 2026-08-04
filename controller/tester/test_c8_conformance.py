"""C8 — handler conformance (PYTHON_CONTROLLER.md §7.3). The 8 core handlers must conform;
the checker must catch the mechanical violations it claims to."""

import controller.step_types  # noqa: F401
from controller.conformance import check_handler, check_source
from controller.registry import STEP_REGISTRY


# ---- the 8 core handlers conform ------------------------------------------

def test_all_core_handlers_conform():
    # The 8 core (primitive) handlers must conform; app step types are checked by CI in
    # their own package, and other tests may register throwaway ones here.
    offenders = {t.type_id: v for t in STEP_REGISTRY.values() if t.kind == "primitive"
                 and (v := check_handler(t.handler_cls))}
    assert offenders == {}, offenders


def test_registry_has_the_eight_core_types():
    assert {"repeat", "sweep", "if", "group", "wait", "prompt_operator",
            "set_output", "measure_and_compare"} <= set(STEP_REGISTRY)


# ---- the checker catches each mechanical rule -----------------------------

def test_flags_bare_time_sleep():
    src = "import time\ndef execute(params, ctx):\n    time.sleep(1)\n"
    assert any("rule1" in e for e in check_source(src))


def test_flags_forbidden_import():
    for mod in ("socket", "nidaqmx", "pyvisa", "sqlite3", "paho"):
        assert any("rule2" in e for e in check_source(f"import {mod}\n")), mod
    assert any("rule2" in e for e in check_source("from serial import Serial\n"))


def test_flags_file_access():
    assert any("rule2" in e for e in check_source("def execute(p, c):\n    open('/x')\n"))


def test_flags_unbounded_loop():
    bad = "def execute(p, ctx):\n    while True:\n        ctx.read('v')\n"
    assert any("rule3" in e for e in check_source(bad))


def test_bounded_loop_with_abort_check_is_ok():
    ok = ("def execute(p, ctx):\n    while True:\n"
          "        if ctx.aborted():\n            break\n        ctx.read('v')\n")
    assert not any("rule3" in e for e in check_source(ok))


def test_while_true_with_break_is_ok():
    ok = "def execute(p, ctx):\n    while True:\n        break\n"
    assert not any("rule3" in e for e in check_source(ok))


def test_flags_module_level_mutable_state():
    assert any("rule4" in e for e in check_source("_cache = {}\n"))
    assert any("rule4" in e for e in check_source("_seen = []\n"))


def test_flags_class_level_mutable_state():
    src = "class H:\n    _state = {}\n    def execute(self, p, c):\n        return None\n"
    assert any("rule4" in e for e in check_source(src))


def test_clean_handler_has_no_violations():
    clean = ("class H:\n"
             "    def execute(self, params, ctx):\n"
             "        v = ctx.read(params['signal'])\n"
             "        ctx.wait(1)\n"
             "        return v\n")
    assert check_source(clean) == []

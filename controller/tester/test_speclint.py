"""spec-lint: the test-spec drift gate (GitHub #5). Broker-free, fixture-driven."""

from controller import speclint


SPEC_AUTHORED = """---
test: ir
type: hipot_ir
kind: authored
spec_source: "UT5320R+ manual §4"
---
# Insulation resistance

## Purpose
Measure IR at each program point.

## Input — recipe parameters
| param | meaning | default | limits |
|---|---|---|---|
| action | hipot action | hipot | — |
| points | IR points | — | — |
| voltage | test voltage | 500 | ≥0 |
| min | IR minimum | — | — |
| unit | unit | MΩ | — |
| step_map | point → step | — | — |

## Output — report measurements
| measurement | unit | judged? | limit source |
|---|---|---|---|
| IR1 | MΩ | yes | params.min |
| IR2 | MΩ | yes | params.min |
| IR3 | MΩ | yes | params.min |

## Signals / actions
| name | dir | via |
|---|---|---|
| hipot | action | ctx.invoke measure_ir |
"""

SPEC_CORE = """---
test: air
type: measure_and_compare
kind: core
---
# Air pressure

## Input — recipe parameters
| param | meaning |
|---|---|

## Output — report measurements
| measurement | unit | judged? |
|---|---|---|
| Air pressure | MPa | yes |

## Signals / actions
| name | dir |
|---|---|
| air_pressure | read |
"""

RECIPE = {
    "recipe_id": "r", "steps": [
        {"type": "group", "id": "ir", "params": {"steps": [
            {"type": "hipot_ir", "id": "ir_meas",
             "params": {"action": "hipot", "points": ["IR1", "IR2", "IR3"], "min": 10}},
        ]}},
        {"type": "group", "id": "air", "params": {"steps": [
            {"type": "measure_and_compare", "id": "air_meas",
             "params": {"signal": "air_pressure", "name": "Air pressure", "unit": "MPa", "min": 0.4, "max": 0.6}},
        ]}},
    ],
}

CATALOG = [
    {"type_id": "hipot_ir", "kind": "application", "required_signals": [], "required_actions": [],
     "schema": {"properties": {"action": {}, "points": {}, "voltage": {}, "min": {}, "unit": {}, "step_map": {}}}},
    {"type_id": "measure_and_compare", "kind": "primitive", "required_signals": [], "required_actions": [],
     "schema": {"properties": {"signal": {}, "name": {}, "unit": {}, "min": {}, "max": {}}}},
]

# what the sim run emitted, per step id
EMITTED = {"ir_meas": ["IR1", "IR2", "IR3"], "air_meas": ["Air pressure"]}
MAP_SIGNALS = {"air_pressure"}


def _write(tmp_path, **files):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


def test_parse_authored_spec():
    sp = speclint.parse_spec(SPEC_AUTHORED)
    assert sp.test == "ir" and sp.type == "hipot_ir" and sp.kind == "authored"
    assert sp.params == {"action", "points", "voltage", "min", "unit", "step_map"}
    assert sp.measurements == {"IR1", "IR2", "IR3"}
    assert sp.signals == {"hipot"}


def test_in_sync(tmp_path):
    _write(tmp_path, **{"ir.md": SPEC_AUTHORED, "air.md": SPEC_CORE})
    rep = speclint.check_specs(tmp_path, RECIPE, CATALOG, EMITTED, MAP_SIGNALS)
    assert rep.ok, rep.summary()
    assert not rep.warnings


def test_missing_spec_is_error(tmp_path):
    _write(tmp_path, **{"ir.md": SPEC_AUTHORED})       # air.md absent
    rep = speclint.check_specs(tmp_path, RECIPE, CATALOG, EMITTED, MAP_SIGNALS)
    assert not rep.ok
    assert any("air" in e and "no specs/air.md" in e for e in rep.errors)


def test_measurement_drift(tmp_path):
    # spec claims an IR4 the run never emits, and drops IR3 that it does
    bad = SPEC_AUTHORED.replace("| IR3 | MΩ | yes | params.min |", "| IR4 | MΩ | yes | params.min |")
    _write(tmp_path, **{"ir.md": bad, "air.md": SPEC_CORE})
    rep = speclint.check_specs(tmp_path, RECIPE, CATALOG, EMITTED, MAP_SIGNALS)
    assert not rep.ok
    assert any("IR4" in e and "not in the code" in e for e in rep.errors)
    assert any("IR3" in e and "missing from the spec" in e for e in rep.errors)


def test_param_drift(tmp_path):
    # spec omits `voltage` and invents `bogus`
    bad = SPEC_AUTHORED.replace("| voltage | test voltage | 500 | ≥0 |\n", "")
    bad = bad.replace("| step_map | point → step | — | — |", "| bogus | nope | — | — |")
    _write(tmp_path, **{"ir.md": bad, "air.md": SPEC_CORE})
    rep = speclint.check_specs(tmp_path, RECIPE, CATALOG, EMITTED, MAP_SIGNALS)
    assert not rep.ok
    assert any("voltage" in e and "missing from the spec" in e for e in rep.errors)
    assert any("bogus" in e and "not in the code" in e for e in rep.errors)


def test_core_signal_not_in_map(tmp_path):
    recipe = {"recipe_id": "r", "steps": [
        {"type": "group", "id": "air", "params": {"steps": [
            {"type": "measure_and_compare", "id": "air_meas",
             "params": {"signal": "ghost", "name": "Air pressure", "unit": "MPa", "min": 0.4}},
        ]}},
    ]}
    spec = SPEC_CORE.replace("| air_pressure | read |", "| ghost | read |")
    _write(tmp_path, **{"air.md": spec})
    rep = speclint.check_specs(tmp_path, recipe, CATALOG, {"air_meas": ["Air pressure"]}, MAP_SIGNALS)
    assert not rep.ok
    assert any("ghost" in e and "not in the variable map" in e for e in rep.errors)


def test_spec_without_recipe_group_warns(tmp_path):
    _write(tmp_path, **{"ir.md": SPEC_AUTHORED, "air.md": SPEC_CORE,
                        "ghost.md": "---\ntest: ghost\nkind: core\n---\n# Ghost\n"})
    rep = speclint.check_specs(tmp_path, RECIPE, CATALOG, EMITTED, MAP_SIGNALS)
    assert rep.ok                          # warnings only
    assert any("ghost" in w and "no matching recipe group" in w for w in rep.warnings)

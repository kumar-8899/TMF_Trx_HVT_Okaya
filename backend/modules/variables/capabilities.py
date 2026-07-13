"""Capability UI catalog — the descriptor that drives the Instrument Test Bench.

One entry per SCALAR capability, listing each method with the control kind + arg
schema the frontend renders (the same "catalog drives the form" pattern as
`modules/config/transports.py`). Aligned with `instrumentlib.interfaces`; a drift
assert (below) fails loudly if a capability method is missing here.

Control kinds the UI knows:
  set    — arg input(s) + Apply           (set_voltage, set_setpoint, write_digital)
  toggle — a single bool switch           (output_enable, load_enable)
  enum   — a select of `options` + Apply  (set_mode)
  read   — Read button + value; arg inputs first if the method takes any
  action — a plain button, no args        (base safe_state / emergency_disable)

Arg types: number | int | bool | enum (with `options`). Units are display-only.
Non-scalar capabilities (multiplexer/dso) are intentionally absent — they are reached
via capability.request, not this manual UI.
"""

from __future__ import annotations

from instrumentlib.interfaces import CAPABILITIES, SCALAR_CAPABILITIES


def _arg(name, type="number", *, unit=None, options=None):
    d = {"name": name, "type": type}
    if unit is not None:
        d["unit"] = unit
    if options is not None:
        d["options"] = options
    return d


def _m(method, kind, label, *, args=None, unit=None):
    d = {"method": method, "kind": kind, "label": label, "args": args or []}
    if unit is not None:
        d["unit"] = unit
    return d


_MODES = ["cc", "cv", "cr", "cp"]

# capability id -> {label, methods[]}. Method order = display order.
CAPABILITY_UI: dict[str, dict] = {
    "power_source": {"label": "Power source", "methods": [
        _m("set_voltage", "set", "Set voltage", args=[_arg("volts", unit="V")]),
        _m("set_current_limit", "set", "Current limit", args=[_arg("amps", unit="A")]),
        _m("output_enable", "toggle", "Output", args=[_arg("on", "bool")]),
        _m("get_voltage_setpoint", "read", "Voltage setpoint", unit="V"),
        _m("measure_voltage", "read", "Measured voltage", unit="V"),
        _m("measure_current", "read", "Measured current", unit="A"),
    ]},
    "electronic_load": {"label": "Electronic load", "methods": [
        _m("set_mode", "enum", "Mode", args=[_arg("mode", "enum", options=_MODES)]),
        _m("set_setpoint", "set", "Setpoint", args=[_arg("value")]),
        _m("load_enable", "toggle", "Load", args=[_arg("on", "bool")]),
        _m("measure_voltage", "read", "Measured voltage", unit="V"),
        _m("measure_current", "read", "Measured current", unit="A"),
        _m("measure_power", "read", "Measured power", unit="W"),
    ]},
    "analog_input": {"label": "Analog input", "methods": [
        _m("read_voltage", "read", "Read voltage", args=[_arg("channel", "int")], unit="V"),
    ]},
    "digital_input": {"label": "Digital input", "methods": [
        _m("read_digital", "read", "Read state", args=[_arg("channel", "int")]),
    ]},
    "digital_output": {"label": "Digital output", "methods": [
        _m("write_digital", "set", "Write state",
           args=[_arg("channel", "int"), _arg("state", "bool")]),
        _m("read_digital_setpoint", "read", "Read setpoint", args=[_arg("channel", "int")]),
    ]},
    "temperature": {"label": "Temperature", "methods": [
        _m("measure_temperature", "read", "Measure temperature",
           args=[_arg("channel", "int")], unit="°"),
    ]},
    "resistance": {"label": "Resistance", "methods": [
        _m("measure_resistance", "read", "Measure resistance",
           args=[_arg("channel", "int")], unit="Ω"),
    ]},
    "frequency": {"label": "Frequency", "methods": [
        _m("measure_frequency", "read", "Measure frequency",
           args=[_arg("channel", "int")], unit="Hz"),
    ]},
}

# The mandatory base surface every InstrumentBase exposes (invoke-able like any method).
# Always available in the panel, even outside maintenance — they only cut outputs.
BASE_ACTIONS: list[dict] = [
    {"method": "safe_state", "kind": "action", "label": "Safe state", "severity": "warning"},
    {"method": "emergency_disable", "kind": "action", "label": "Emergency disable", "severity": "error"},
]


def _assert_no_drift() -> None:
    """Every scalar-capability method in interfaces.py must be described here."""
    for cap in SCALAR_CAPABILITIES:
        want = set(CAPABILITIES[cap].METHODS)
        have = {m["method"] for m in CAPABILITY_UI.get(cap, {}).get("methods", [])}
        missing = want - have
        assert not missing, f"capability '{cap}' missing UI descriptors for: {sorted(missing)}"
    assert not (CAPABILITY_UI.keys() - SCALAR_CAPABILITIES), \
        "CAPABILITY_UI has a non-scalar / unknown capability"


_assert_no_drift()


def catalog() -> dict:
    return {"capabilities": CAPABILITY_UI, "base_actions": BASE_ACTIONS}

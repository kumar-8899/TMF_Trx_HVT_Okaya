"""Tests for the System Blueprint authoring tool (tools/blueprint).

Covers the plan's verification: template shape, reader round-trip (TBD -> None),
partial-sheet generation (pending signals not emitted), in-place reconcile
(rename by tag / add / keep-dropped), multiplexing (scan points are ordinary
signals, DOs are not signals, composite spec emitted), and that the generated map
matches the controller-side variable-map shape.
"""

from __future__ import annotations

import json

from openpyxl import Workbook, load_workbook

from tools.blueprint import catalog, template
from tools.blueprint.generate import generate
from tools.blueprint.reader import Blueprint, read_workbook

# Keys the controller variable engine reads from a signal binding (plus our forward-
# looking range/deadband metadata). No binding may carry anything outside this set.
_ALLOWED_BINDING_KEYS = {"instance", "read", "write", "args", "scale", "clamp",
                         "units", "range", "deadband"}


# --------------------------------------------------------------------------- template


def test_make_template_has_the_four_sheets_and_headers(tmp_path):
    out = template.make_template(tmp_path / "bp.xlsx")
    wb = load_workbook(out)
    assert wb.sheetnames == ["Read me", "Instruments", "Signals", "Actions", "Multiplexing"]
    assert [c.value for c in wb["Signals"][1]][:4] == ["tag", "name", "station",
                                                       "instrument_tag"]
    # capability + transport vocab is surfaced live from the framework code
    assert "power_source" in "".join(str(r[1].value) for r in wb["Read me"].iter_rows())


def test_template_is_reproducible_and_readable_back_as_empty(tmp_path):
    out = template.make_template(tmp_path / "bp.xlsx")
    bp = read_workbook(out)
    # only the italic "# example ->" rows exist, and those are skipped by the reader
    assert bp.instruments == [] and bp.signals == []


# ----------------------------------------------------------------------------- reader


def _wb_with(path, sheet, cols, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    wb.save(path)


def test_reader_normalizes_blank_and_tbd_to_none(tmp_path):
    p = tmp_path / "s.xlsx"
    _wb_with(p, "Signals",
             ["tag", "name", "station", "instrument_tag", "read", "channel"],
             [{"tag": "sv", "name": "supply_voltage", "station": "st1",
               "instrument_tag": "psu", "read": "measure_voltage", "channel": "TBD"},
              {"tag": None, "name": None}])  # blank row skipped
    bp = read_workbook(p)
    assert len(bp.signals) == 1
    assert bp.signals[0]["channel"] is None       # TBD -> None
    assert bp.signals[0]["read"] == "measure_voltage"


# --------------------------------------------------------------------------- generate


def _partial() -> Blueprint:
    return Blueprint(
        instruments=[{"tag": "psu", "id": "psu1", "owner": "python",
                      "library": "keysight_e36313a", "capabilities": "power_source",
                      "connection": "resource=TCPIP0::10.0.0.5::INSTR",
                      "simulated": "true", "status": "known"}],
        signals=[
            {"tag": "sv", "name": "supply_voltage", "station": "st1",
             "instrument_tag": "psu", "read": "measure_voltage", "write": "set_voltage",
             "clamp_min": "0", "clamp_max": "30", "units": "V"},
            {"tag": "sc", "name": "supply_current", "station": "st1",
             "instrument_tag": "psu", "read": "measure_current", "units": "A"},
            {"tag": "aux", "name": "aux_temp", "station": "st1", "instrument_tag": "psu"},
        ],
    )


def test_partial_sheet_generates_map_and_keeps_incomplete_signal_pending(tmp_path):
    rep = generate(_partial(), tmp_path, "demo")
    assert rep.ok, rep.errors
    m = json.loads((tmp_path / "app/demo/maps/st1.json").read_text())
    assert set(m["signals"]) == {"supply_voltage", "supply_current"}   # aux_temp pending
    assert m["signals"]["supply_voltage"] == {
        "instance": "psu1", "read": "measure_voltage", "write": "set_voltage",
        "clamp": {"min": 0, "max": 30}, "units": "V"}
    for b in m["signals"].values():
        assert set(b) <= _ALLOWED_BINDING_KEYS
    assert any("aux_temp" in p for p in rep.pending)
    assert (tmp_path / "app/demo/maps/.blueprint.lock.json").exists()
    inst_md = (tmp_path / "app/demo/docs/INSTRUMENTS.md").read_text()
    assert "psu1" in inst_md and "keysight_e36313a" in inst_md


def test_unknown_read_method_is_a_blocking_error(tmp_path):
    bp = _partial()
    bp.signals[0]["read"] = "measure_torque"   # not a power_source method
    rep = generate(bp, tmp_path, "demo")
    assert not rep.ok
    assert any("measure_torque" in e for e in rep.errors)
    assert not (tmp_path / "app/demo/maps/st1.json").exists()   # nothing written on error


def test_reconcile_updates_in_place_by_tag(tmp_path):
    generate(_partial(), tmp_path, "demo")               # first, partial
    fuller = _partial()
    fuller.instruments.append({"tag": "dmm", "id": "dmm1", "owner": "python",
                               "library": "keysight_34461a", "capabilities": "resistance",
                               "connection": "resource=TCPIP0::10.0.0.6::INSTR"})
    # rename supply_current -> rail_current (SAME tag sc); add a channelled DMM read;
    # drop supply_voltage (remove tag sv) -> should be kept-and-warned.
    fuller.signals = [
        {"tag": "sc", "name": "rail_current", "station": "st1", "instrument_tag": "psu",
         "read": "measure_current", "units": "A"},
        {"tag": "dr", "name": "dut_resistance", "station": "st1", "instrument_tag": "dmm",
         "read": "measure_resistance", "channel": "104", "units": "ohm"},
        {"tag": "aux", "name": "aux_temp", "station": "st1", "instrument_tag": "psu"},
    ]
    rep = generate(fuller, tmp_path, "demo")
    assert rep.ok, rep.errors
    m = json.loads((tmp_path / "app/demo/maps/st1.json").read_text())
    assert "rail_current" in m["signals"] and "supply_current" not in m["signals"]  # renamed
    assert m["signals"]["dut_resistance"]["args"] == [104]                          # channel
    assert "supply_voltage" in m["signals"]                                         # kept
    assert any("renamed" in c for c in rep.changed)
    assert any("dut_resistance" in a for a in rep.added)
    assert any("supply_voltage" in r for r in rep.removed)


def test_prune_drops_signals_removed_from_the_sheet(tmp_path):
    generate(_partial(), tmp_path, "demo")
    fuller = _partial()
    fuller.signals = [s for s in fuller.signals if s["tag"] != "sv"]   # drop supply_voltage
    rep = generate(fuller, tmp_path, "demo", prune=True)
    m = json.loads((tmp_path / "app/demo/maps/st1.json").read_text())
    assert "supply_voltage" not in m["signals"]
    assert rep.ok


def test_labview_signal_is_inventory_only(tmp_path):
    bp = Blueprint(
        instruments=[{"tag": "lv", "id": "lv_ai", "owner": "labview",
                      "transport": "nidaq", "connection": "device=Dev1; channel=ai0",
                      "capabilities": "analog_input"}],
        signals=[{"tag": "x", "name": "cell_v", "station": "st1", "instrument_tag": "lv",
                  "read": "read_voltage", "channel": "0", "units": "V"}])
    rep = generate(bp, tmp_path, "demo")
    assert rep.ok, rep.errors
    # LabVIEW-owned signals are inventory only — nothing to emit, so no controller map
    assert not (tmp_path / "app/demo/maps/st1.json").exists()
    assert (tmp_path / "app/demo/docs/INSTRUMENTS.md").exists()
    assert any("LabVIEW-owned" in w for w in rep.warnings)


# ------------------------------------------------------------------------ multiplexing


def test_multiplexing_scan_points_are_signals_and_dos_are_not(tmp_path):
    bp = Blueprint(
        instruments=[
            {"tag": "scan", "id": "cell_scanner", "owner": "python",
             "library": "acme_cellscanner", "capabilities": "analog_input",
             "connection": "resource=X"},
            {"tag": "daq", "id": "daq1", "owner": "labview", "transport": "nidaq",
             "connection": "device=Dev1; channel=ai0", "capabilities": "analog_input"},
            {"tag": "relays", "id": "relaybank", "owner": "labview", "transport": "nidaq",
             "connection": "device=Dev1; channel=port0", "capabilities": "digital_output"},
        ],
        signals=[
            {"tag": f"c{n}", "name": f"cell_{n}_voltage", "station": "st1",
             "instrument_tag": "scan", "read": "read_voltage", "channel": str(n),
             "units": "V"} for n in range(1, 4)
        ],
        mux=[
            {"tag": f"m{n}", "logical_signal": f"cell_{n}_voltage",
             "measure_instrument_tag": "daq", "measure_method": "read_voltage",
             "measure_channel": "0", "selector_instrument_tag": "relays",
             "select_by": "relay_pattern", "relay_pattern": f"do0={n & 1},do1={n >> 1}",
             "settle_ms": "5"} for n in range(1, 4)
        ],
    )
    rep = generate(bp, tmp_path, "demo")
    assert rep.ok, rep.errors
    m = json.loads((tmp_path / "app/demo/maps/st1.json").read_text())
    assert set(m["signals"]) == {"cell_1_voltage", "cell_2_voltage", "cell_3_voltage"}
    assert m["signals"]["cell_2_voltage"]["args"] == [2]        # channel = scan position
    # no digital output ever became a signal
    assert not any("relay" in name or "do" == name for name in m["signals"])
    mux_md = (tmp_path / "app/demo/docs/MULTIPLEXING.md").read_text()
    assert "cell_scanner" in mux_md and "settle" in mux_md.lower()
    assert any("cell_3_voltage" in x for x in rep.mux)


# ------------------------------------------------------------------------------ catalog


def test_catalog_fixed_arg_arity_matches_the_engine_convention():
    reads = catalog.read_methods_for(["analog_input", "power_source"])
    writes = catalog.write_methods_for(["power_source", "digital_output"])
    assert reads["read_voltage"] == 1          # read_voltage(channel)
    assert reads["measure_voltage"] == 0       # measure_voltage()
    assert writes["set_voltage"] == 0          # set_voltage(value) -> value is written
    assert writes["write_digital"] == 1        # write_digital(channel, value)

"""The wide-row builder against the customer's `txr_testtable_hv.xlsx` template and its sample row."""

import datetime as dt
from pathlib import Path

import pytest

from modules.okaya_mes import rowbuilder as rb

TEMPLATE = Path(__file__).resolve().parents[4] / "app" / "okaya_hvt" / "docs" / "okaya_mes_txr_testtable_hv.xlsx"


def _ts(*hms) -> float:
    return dt.datetime(2026, 10, 26, *hms).timestamp()


def _res(key, label, value, status="PASS", *, mx=10.0, mn=None):
    return {"step_id": f"{key}_hipot", "name": label, "test_name": label, "value": value, "unit": "mA",
            "limits": {"min": mn, "max": mx, "expected": None}, "status": status, "result": status}


def _run(results, **over):
    run = {"run_id": "r1", "serial_no": "O1ZD10ATXR0010042", "recipe_id": "001", "operator": "operator",
           "started_ts": _ts(18, 1, 29), "finished_ts": _ts(18, 2, 44), "result": "PASS", "results": results}
    run.update(over)
    return run


ALL_PASS = [_res("pri_sec", "Primary to Secondary", 0.52), _res("pri_core", "Primary to Core", 0.35),
            _res("sec_core", "Secondary to Core", 0.40), _res("fb_core", "Feedback to Core", 0.22),
            _res("pri_fb", "Primary to Feedback", 0.56), _res("sec_fb", "Secondary to Feedback", 0.35)]


def test_columns_are_exactly_the_customers_template_in_order():
    openpyxl = pytest.importorskip("openpyxl")
    ws = openpyxl.load_workbook(TEMPLATE).active
    assert [c.value for c in ws[1]] == list(rb.COLUMNS)
    assert len(rb.COLUMNS) == 32


def test_header_fields_follow_the_agreed_rules():
    row = rb.build_row(_run(ALL_PASS), station_name="HV Testing")
    assert row["date_time"] == dt.datetime(2026, 10, 26, 18, 2, 44)       # run FINISH time, no microseconds
    assert row["serial_no"] == "O1ZD10ATXR0010042"
    assert row["model_name"] == "001" and isinstance(row["model_name"], str)   # recipe ID as TEXT
    assert row["test_time"] == " 1:15"                                    # m:ss, minutes right-aligned to 2
    assert row["operator_name"] == "operator" and row["station_name"] == "HV Testing"


def test_pass_row_matches_the_legacy_formatting():
    row = rb.build_row(_run(ALL_PASS))
    assert (row["hv_pri_to_sec_winding_min"], row["hv_pri_to_sec_winding_max"],
            row["hv_pri_to_sec_winding_actual"], row["hv_pri_to_sec_winding_result"]) == ("0", "10", "0.52", "Pass")
    assert row["hv_primary_to_feedback_winding_actual"] == "0.56"
    assert row["result"] == "Pass" and row["failed_test"] is None            # NULL, not the string 'NULL'


def test_a_recipe_min_is_kept_and_only_a_missing_min_becomes_zero():
    res = [_res("pri_sec", "Primary to Secondary", 0.52, mn=0.1)]
    row = rb.build_row(_run(res))
    assert row["hv_pri_to_sec_winding_min"] == "0.1"


def test_tests_that_did_not_run_are_null_in_all_four_columns():
    row = rb.build_row(_run([_res("pri_sec", "Primary to Secondary", 0.5)]))
    for stem in ("hv_pri_to_core_winding", "hv_sec_to_core_winding", "hv_feedback_to_core_winding",
                 "hv_primary_to_feedback_winding", "hv_secondary_to_feedback_winding"):
        assert [row[f"{stem}_{p}"] for p in ("min", "max", "actual", "result")] == [None] * 4   # not 'NaN'


def test_failed_test_is_the_first_failure_in_execution_order_as_the_column_stem():
    res = [_res("pri_sec", "Primary to Secondary", 0.5),
           _res("pri_core", "Primary to Core", 12.0, "FAIL"),
           _res("sec_core", "Secondary to Core", 11.0, "FAIL")]
    row = rb.build_row(_run(res, result="FAIL"))
    assert row["result"] == "Fail"
    assert row["failed_test"] == "hv_pri_to_core_winding"                  # first one, as the column stem
    assert row["hv_pri_to_core_winding_result"] == "Fail" and row["hv_sec_to_core_winding_result"] == "Fail"


def test_a_stop_on_fail_run_leaves_the_skipped_tests_null():
    res = [_res("pri_sec", "Primary to Secondary", 0.5), _res("pri_core", "Primary to Core", 12.0, "FAIL")]
    row = rb.build_row(_run(res, result="FAIL"))
    assert row["hv_sec_to_core_winding_actual"] is None                    # skipped: no row, so NULL
    assert row["hv_secondary_to_feedback_winding_result"] is None
    assert row["failed_test"] == "hv_pri_to_core_winding"


def test_a_tester_error_row_is_written_as_ERROR_and_Fail():
    res = [_res("pri_core", "Primary to Core", "ERROR", "FAIL")]
    row = rb.build_row(_run(res, result="FAIL"))
    assert row["hv_pri_to_core_winding_actual"] == "ERROR" and row["hv_pri_to_core_winding_result"] == "Fail"
    assert row["failed_test"] == "hv_pri_to_core_winding"


def test_old_result_names_and_missing_step_ids_still_map():
    old = {"name": "feedback", "value": 1.2}
    res = [{"name": "pri_sec_leakage_current", "value": 0.4, "limits": {"min": None, "max": 5.0, "expected": None},
            "status": "PASS"}, old]
    row = rb.build_row(_run(res))
    assert row["hv_pri_to_sec_winding_actual"] == "0.4" and row["hv_pri_to_sec_winding_max"] == "5"


def test_an_unmapped_failing_test_still_names_the_failure():
    res = [{"step_id": "mystery", "name": "Mystery test", "value": 9, "status": "FAIL",
            "limits": {"min": None, "max": 1.0, "expected": None}}]
    row = rb.build_row(_run(res, result="FAIL"))
    assert row["failed_test"] == "Mystery test"


@pytest.mark.parametrize("secs,text", [(75, " 1:15"), (59.6, " 1:00"), (5, " 0:05"), (3725, "62:05"), (600, "10:00")])
def test_test_time_format(secs, text):
    assert rb.test_time_text(100.0, 100.0 + secs) == text


def test_test_time_is_null_without_timestamps_or_when_negative():
    assert rb.test_time_text(None, 5) is None and rb.test_time_text(10, 5) is None


@pytest.mark.parametrize("v,s", [(0, "0"), (0.0, "0"), (10.0, "10"), (0.52, "0.52"), (215.4, "215.4"), (0.0554, "0.0554"),
                                 (0.05549, "0.0555"), (float("nan"), None), (None, None), ("ERROR", "ERROR")])
def test_number_formatting(v, s):
    assert rb.fmt_number(v) == s


def test_text_is_capped_at_varchar_50_and_blank_is_null():
    row = rb.build_row(_run(ALL_PASS, operator="x" * 80, serial_no="  "))
    assert len(row["operator_name"]) == 50 and row["serial_no"] is None


def test_every_row_carries_every_column():
    assert set(rb.build_row({})) == set(rb.COLUMNS)


def test_overall_result_text():
    assert rb.build_row(_run([], result="PASS"))["result"] == "Pass"
    assert rb.build_row(_run([], result="FAIL"))["result"] == "Fail"
    assert rb.build_row(_run([], result="ABORTED"))["result"] == "Aborted"

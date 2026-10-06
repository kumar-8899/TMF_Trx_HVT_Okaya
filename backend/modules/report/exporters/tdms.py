"""TDMS exporter — flat single group.

One group (`Reports`) holds every column as a channel of equal length, so row n of every channel is
DUT n. Channel order: the fixed DUT columns, then for each test one channel per selected parameter
field, named "<test> - <Field label>". Numeric fields (Measured Value, Cycle Time in seconds) are
float64 with NaN for "no value"; a measured column that contains any non-numeric text is written as a
string channel instead so no information is lost. Expected Value / Result are string channels.
"""

from __future__ import annotations

import datetime as _dt
import io
import json

from modules.report.exporters.spec import (
    ExportSpec, ExportUnavailable, fixed_value, param_value, to_number,
)

GROUP = "Reports"


def build(matrix: dict, spec: ExportSpec, meta: dict | None = None) -> bytes:
    try:
        import numpy as np
        from nptdms import ChannelObject, GroupObject, RootObject, TdmsWriter
    except ModuleNotFoundError as exc:      # pragma: no cover — declared runtime dependency
        raise ExportUnavailable("TDMS export needs the 'nptdms' package (pip install nptdms).") from exc

    meta = meta or {}
    tests = list(matrix.get("tests") or [])
    rows = list(matrix.get("rows") or [])
    channels: list = []
    used: set[str] = set()

    def add(name: str, values: list, props: dict | None = None, *, numeric: bool = False) -> None:
        base, n = name, 2
        while name in used:                          # channel names are unique within a group
            name, n = f"{base} ({n})", n + 1
        used.add(name)
        if numeric or not values:
            # nptdms cannot infer a type for an EMPTY string array, so a zero-row export writes
            # (empty) float channels — still a valid file with every channel name present.
            data = np.array([np.nan if v is None else v for v in values], dtype=np.float64)
        else:
            data = np.array(["" if v is None else str(v) for v in values], dtype=object)
        channels.append(ChannelObject(GROUP, name, data, props or {}))

    for col in spec.fixed:
        vals = [fixed_value(r, col) for r in rows]
        if col == "cycle_s":
            add(col, [to_number(v) for v in vals], {"unit_string": "s"}, numeric=True)
        else:
            add(col, [v.isoformat() if isinstance(v, (_dt.date, _dt.time)) else v for v in vals])

    for name in tests:
        cells = [r.get(name) if isinstance(r.get(name), dict) else None for r in rows]
        unit = next((c.get("unit") for c in cells if c and c.get("unit")), None)
        for field in spec.fields:
            raw = [param_value(c, field) for c in cells]
            ch_name = f"{name} - {spec.label(field)}"
            props = {"test_name": name, "field": field}
            if field == "cycle":
                add(ch_name, [to_number(v) for v in raw], {**props, "unit_string": "s"}, numeric=True)
            elif field == "measured":
                nums = [to_number(v) for v in raw]
                if all(n is not None for n, v in zip(nums, raw) if v not in (None, "")):
                    add(ch_name, nums, {**props, **({"unit_string": unit} if unit else {})}, numeric=True)
                else:                                # mixed/text measurements: keep them verbatim
                    add(ch_name, raw, props)
            else:
                add(ch_name, raw, props)

    root = {
        "title": "Test report export",
        "station": str(meta.get("station") or ""),
        "exported_at": meta.get("exported_at") or _dt.datetime.now().isoformat(timespec="seconds"),
        "row_count": len(rows),
        "tests": json.dumps(tests, ensure_ascii=False),
        "fields": ",".join(spec.fields),
        "filters": json.dumps(meta.get("filters") or {}, ensure_ascii=False, default=str),
    }
    buf = io.BytesIO()
    with TdmsWriter(buf) as writer:
        writer.write_segment([RootObject(root), GroupObject(GROUP, {"description": "One row per DUT"}),
                              *channels])
    return buf.getvalue()

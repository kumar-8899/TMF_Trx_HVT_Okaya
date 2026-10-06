"""Export spec — which DUT columns and which per-test parameter fields go into an export.

The bulk report export is a *matrix*: one row per DUT (run), fixed DUT columns first, then for each
test a block of parameter columns. The parameter fields are selectable; an unticked field is absent
under EVERY test (never a half-empty column). Adding a field or a DUT column is one line here — the
format writers (xlsx, tdms, …) are driven by these tables, never by hard-coded column lists.
"""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass


class ExportError(ValueError):
    """Bad export request (unknown format/field, nothing selected, too big). Maps to HTTP 422
    (409 when the request is fine but the station can't serve it, e.g. no report database yet)."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


class ExportUnavailable(RuntimeError):
    """A required library is not installed on this station. Maps to HTTP 501."""


# (id, label) — order is the column order under every test.
PARAM_FIELDS: tuple[tuple[str, str], ...] = (
    ("expected", "Expected Value"),
    ("measured", "Measured Value"),
    ("result", "Result"),
    ("cycle", "Cycle Time"),
)

# (id, default_on) — the header text IS the id (same as the customer template).
FIXED_COLUMNS: tuple[tuple[str, bool], ...] = (
    ("serial_no", True), ("model", True), ("recipe_id", True), ("result", True),
    ("business_day", True), ("shift_label", True), ("date", True), ("time", True),
    ("operator", True), ("cycle_s", True),
    ("station", False), ("run_id", False),
)

_FIELD_IDS = tuple(f for f, _ in PARAM_FIELDS)
_FIELD_LABEL = dict(PARAM_FIELDS)
_FIXED_IDS = tuple(c for c, _ in FIXED_COLUMNS)
_FIXED_DEFAULT = tuple(c for c, on in FIXED_COLUMNS if on)


def catalog() -> dict:
    """What the UI needs to build its controls (served by GET /reports/export/formats)."""
    return {
        "fields": [{"id": i, "label": lbl} for i, lbl in PARAM_FIELDS],
        "columns": [{"id": c, "label": c, "default": on} for c, on in FIXED_COLUMNS],
    }


@dataclass(frozen=True)
class ExportSpec:
    fixed: tuple[str, ...] = _FIXED_DEFAULT
    fields: tuple[str, ...] = _FIELD_IDS

    @classmethod
    def parse(cls, columns: str | None = None, fields: str | None = None) -> ExportSpec:
        """Build from the comma-separated query values. None = default (all); '' = nothing selected."""
        return cls(fixed=_pick(columns, _FIXED_IDS, _FIXED_DEFAULT, "column", allow_empty=False),
                   fields=_pick(fields, _FIELD_IDS, _FIELD_IDS, "parameter field", allow_empty=False))

    def label(self, field: str) -> str:
        return _FIELD_LABEL[field]


def _pick(raw, valid, default, what, *, allow_empty) -> tuple[str, ...]:
    if raw is None:
        return tuple(default)
    wanted = [p.strip() for p in raw.split(",") if p.strip()]
    if not wanted and not allow_empty:
        raise ExportError(f"Select at least one {what} to export.")
    bad = [w for w in wanted if w not in valid]
    if bad:
        raise ExportError(f"Unknown {what}: {', '.join(bad)}. Valid: {', '.join(valid)}.")
    # keep the canonical order regardless of how the client ordered them
    return tuple(v for v in valid if v in wanted)


# --- value access (shared by every format writer) ---------------------------------------------

def _local(ts) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromtimestamp(float(ts)) if ts not in (None, "") else None
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def fixed_value(row: dict, col: str):
    """Typed value of a DUT column. date/time derive from the run's finish (else start) time,
    in the station PC's local zone (matching what the operator saw on the shop floor)."""
    if col in ("date", "time"):
        when = _local(row.get("finished_ts")) or _local(row.get("started_ts"))
        if when is None:
            return None
        return when.date() if col == "date" else when.time().replace(microsecond=0)
    if col == "business_day":
        v = row.get("business_day")
        try:
            return _dt.date.fromisoformat(v) if v else None
        except (TypeError, ValueError):
            return v
    return row.get(col)


def param_value(cell: dict | None, field: str):
    """Raw value of one parameter field of a test cell ({expected, measured, result, cycle_s, unit})."""
    if not cell:
        return None
    return cell.get("cycle_s" if field == "cycle" else field)


def to_number(v) -> float | None:
    """Float if `v` is a plain number (or numeric string), else None. bool is not a number here."""
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v) if isinstance(v, (int, float)) else float(str(v).strip())
    except ValueError:
        return None
    return n if math.isfinite(n) else None     # 'nan' / 'inf' text stays text

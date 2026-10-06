"""Report exporters — a registry of bulk-export formats.

A format is one function `build(matrix, spec, meta) -> bytes` plus its metadata. Adding PDF/…
later = a new module + one `register_format` call; the API, the formats catalog and the UI
dropdown pick it up with no other change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from modules.report.exporters.spec import (
    ExportError, ExportSpec, ExportUnavailable, catalog,
)

__all__ = ["ExportError", "ExportSpec", "ExportUnavailable", "FORMATS", "register_format",
           "get_format", "formats_catalog"]


@dataclass(frozen=True)
class ExportFormat:
    id: str
    label: str
    ext: str
    media_type: str
    build: Callable[[dict, ExportSpec, dict | None], bytes]


FORMATS: dict[str, ExportFormat] = {}


def register_format(fmt: ExportFormat) -> None:
    FORMATS[fmt.id] = fmt


def get_format(fmt_id: str) -> ExportFormat:
    try:
        return FORMATS[fmt_id]
    except KeyError:
        raise ExportError(f"Unknown export format '{fmt_id}'. Available: {', '.join(FORMATS)}.") from None


def formats_catalog() -> dict:
    return {"formats": [{"id": f.id, "label": f.label, "ext": f.ext} for f in FORMATS.values()],
            **catalog()}


def _register_builtin() -> None:
    from modules.report.exporters import tdms, xlsx
    register_format(ExportFormat(
        "xlsx", "Excel (.xlsx)", "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", xlsx.build))
    register_format(ExportFormat("tdms", "TDMS (.tdms)", "tdms", "application/octet-stream", tdms.build))


_register_builtin()

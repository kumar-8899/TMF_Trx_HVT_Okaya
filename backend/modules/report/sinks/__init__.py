"""Report sinks — the pluggable destinations a finished report is routed to.

RP1: sqlite only. RP2 adds the folder sink + make_sink(config). The sqlite sink
is always present (the queryable store); other sinks are result-routed mirrors.
"""

from __future__ import annotations

from modules.report.sinks.folder import FolderSink
from modules.report.sinks.sqlite import SqliteSink


def when_matches(when: str, is_pass: bool) -> bool:
    return when == "all" or (when == "pass" and is_pass) or (when == "fail" and not is_pass)


def make_sink(spec: dict, db):
    t = spec.get("type")
    when = spec.get("when", "all")
    if t == "sqlite":
        return SqliteSink(db, when)
    if t == "folder":
        return FolderSink(spec["path"], when, spec.get("format", "json"))
    if t == "mysql":
        # Seam built, impl deferred — fail loud at config-load (RP plan).
        raise ValueError("mysql report sink needs the 'mysql' extra (not built); use sqlite or folder")
    raise ValueError(f"unknown report sink type '{t}'")


def build_sinks(config: dict, db) -> list:
    """Optional mirror sinks only. The report system-of-record is the professional DB
    (ReportStore) via the local outbox — the old SQLite SoR sink is retired. Only
    'folder' mirror specs are built; legacy 'sqlite'/'mysql' specs are ignored."""
    return [make_sink(s, db) for s in (config.get("sinks") or []) if s.get("type") == "folder"]

"""TMF Debug Tool - the separately installable debugging application for a client PC (docs/DEBUG_TOOL.md).

One program, three roles: an operator-facing UI + live collectors + an MCP server (connected mode); a one-click
diagnostics-bundle collector (air-gapped mode); and the analyser that reads a bundle back (developer's machine).
It reuses `backend/debug_server` (recorder, ring, rolling sink, snapshots, auth, export) and `tmf_debug` (digest,
analysis) instead of re-implementing them. Versioned independently of the framework: see VERSION and COMPAT.json.
"""

from pathlib import Path

try:
    VERSION = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8").strip()
except OSError:                                # frozen builds ship VERSION beside the package
    VERSION = "0.0.0"

__version__ = VERSION

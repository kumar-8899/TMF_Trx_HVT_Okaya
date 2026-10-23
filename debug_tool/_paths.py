"""Make a source checkout runnable: `python -m debug_tool` needs `backend/` (debug_server, core) and the repo root
(tmf_debug) importable. Frozen builds bundle them, so this is a no-op there."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_source_paths() -> None:
    root = Path(__file__).resolve().parents[1]
    if (root / "backend" / "debug_server").is_dir():
        for p in (root, root / "backend"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))

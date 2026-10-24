"""Make `backend/` (debug_server, core) and the repo root (tmf_debug, debug_tool) importable when these testers are
run directly (`python -m pytest debug_tool/tester`)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

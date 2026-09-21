"""Save bytes to the station PC's Downloads folder (the native pywebview window can't do a browser
blob-download reliably — no flyout, unknown location). The station is a LOCAL app (backend + UI on one
PC), so a server-side save lands on the operator's own machine. The filename gets a timestamp so nothing
is overwritten silently. (The report module keeps its own older copy of this; new code uses this one.)"""

from __future__ import annotations

import re
import time
from pathlib import Path


def save_to_downloads(data: bytes, filename: str) -> dict:
    base = Path.home() / "Downloads"
    dest_dir = base if base.is_dir() else Path.home()
    safe = re.sub(r'[\\/:*?"<>|]+', "_", Path(filename).name) or "download"
    stem, dot, ext = safe.rpartition(".")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = dest_dir / (f"{stem}-{stamp}.{ext}" if dot else f"{safe}-{stamp}")
    out.write_bytes(data)
    return {"saved": True, "path": str(out), "filename": out.name, "bytes": len(data)}

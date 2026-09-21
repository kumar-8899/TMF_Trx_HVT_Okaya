"""Where documentation and app-owned portal content live, across source + frozen layouts.

Shared by the help module (manual pages) and the portal module (library seeds, and later the
assistant's corpus) so neither depends on the other — CORE.md §6.1: modules use core, never siblings.

  docs root      `docs/` — the framework docs tree. Frozen (v1.12.0+): `run.dist/docs`, which build_release
                 fills with the USER allowlist only (developer docs are never shipped).
  app portal     `app/<name>/portal/` — app-OWNED content (extra manual pages, images, bundled PDFs).
                 Frozen: `run.dist/app/<name>/portal/` (build_release.copy_app_payload).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]          # backend/core/services/docs_paths.py -> repo root


def resolve_docs_root() -> Path:
    """Locate the `docs/` tree across source + frozen layouts. Frozen (v1.12.0+): docs ride INSIDE
    run.dist (the swap unit), so an update refreshes the in-app help and the published .zip is
    complete — prefer run.dist/docs over a legacy deploy-root copy a swap would leave stale."""
    env = os.environ.get("TMF_DOCS_DIR")
    if env:
        return Path(env)
    exe_dir = Path(sys.executable).resolve().parent
    for cand in (exe_dir / "docs",             # frozen: run.dist/docs (primary)
                 _REPO / "docs",               # source checkout: repo/docs
                 exe_dir.parent / "docs"):     # legacy deploy-root
        if (cand / "help").is_dir():
            return cand.resolve()
    return _REPO / "docs"


def _app_roots() -> list[Path]:
    env = os.environ.get("TMF_APP_DIR")
    if env:
        return [Path(env)]
    exe_dir = Path(sys.executable).resolve().parent
    return [exe_dir / "app", _REPO / "app"]          # frozen run.dist/app first, then a source checkout


def app_portal_dirs() -> list[Path]:
    """Every `app/<name>/portal/` directory that exists (sorted). Usually exactly one — a fork has one
    app — but the framework repo itself, or a multi-app checkout, may have none or several."""
    out: list[Path] = []
    for root in _app_roots():
        if not root.is_dir():
            continue
        for portal in sorted(root.glob("*/portal")):
            if portal.is_dir() and portal.resolve() not in out:
                out.append(portal.resolve())
        if out:
            break                                    # first root that has any wins (frozen over source)
    return out

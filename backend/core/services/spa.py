"""Serve the built React SPA from the Python edge (single-origin production).

In dev the app runs as two processes (Vite on :5173 proxying the REST/WS edge on
:8000). A shipped station has no Vite: the backend itself serves the built bundle
so the whole app — UI + REST + WebSockets — lives on one origin at :8000, and the
one-click launcher only has to open http://127.0.0.1:8000.

The one wrinkle is that the API and the SPA share a path namespace: the runs
module serves `GET /runs` as JSON, while the browser navigates to `/runs` for the
page. The dev Vite proxy (`frontend/vite.config.ts` `serveSpa`) disambiguates by
the `Accept` header — a `text/html` navigation gets index.html, everything else
proxies to the API. `install_spa` mirrors that exactly, as an HTTP middleware that
runs ahead of routing:

  GET, real file under dist/ (assets, favicon)        -> that file
  GET, Accept: text/html (a browser navigation)       -> index.html (the SPA shell)
  everything else (JSON/WS/API clients)               -> normal routing

So a hard refresh on /runs returns the SPA, while `fetch("/runs")` still reaches
the runs API. When no built bundle is present (a pure-Vite dev checkout) nothing
is installed and the edge is API-only, unchanged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse


def resolve_frontend_dist() -> Path | None:
    """Locate the built SPA (`index.html`) across the source and frozen layouts.

    - `TMF_FRONTEND_DIR` env override (deployment escape hatch);
    - source checkout:  <repo>/frontend/dist  (this file = backend/core/services/spa.py);
    - Nuitka release (SECURE_DISTRIBUTION.md §5): run.exe in release-build/run.dist/,
      the bundle copied to release-build/frontend/ (build_release.py) — i.e. beside the
      executable dir's parent.
    Returns the first directory that actually contains an index.html, else None.
    """
    candidates: list[Path] = []
    env = os.environ.get("TMF_FRONTEND_DIR")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "frontend" / "dist")   # <repo>/frontend/dist
    exe_dir = Path(sys.executable).resolve().parent            # frozen: .../run.dist
    candidates.append(exe_dir.parent / "frontend")             # release-build/frontend
    candidates.append(exe_dir / "frontend")
    for cand in candidates:
        try:
            if (cand / "index.html").is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


def install_spa(app: FastAPI, dist: Path) -> None:
    """Mount SPA serving for `dist` (mirrors the dev Vite `serveSpa` bypass).

    Registered as HTTP middleware so it wraps all routing and never depends on the
    order module routers mount in — a real static file or an html navigation is
    answered here; anything else falls through to the API/WS routes untouched.
    """
    dist = dist.resolve()
    index = dist / "index.html"

    @app.middleware("http")
    async def spa_mw(request: Request, call_next):
        if request.method in ("GET", "HEAD"):
            rel = request.url.path.lstrip("/")
            if rel:
                # A real bundled file (assets/*, favicon, …) — serve it directly.
                candidate = (dist / rel).resolve()
                if dist in candidate.parents and candidate.is_file():
                    return FileResponse(candidate)
            # A browser navigation (root or client-side route) — hand back the shell
            # and let the React router take it. API clients (Accept: application/json)
            # and WebSockets fall through to real routes.
            if "text/html" in request.headers.get("accept", ""):
                return FileResponse(index)
        return await call_next(request)

"""App factory + lifespan (CORE.md §5).

P1 scaffold: only the web shell + /healthz exist. Core services, the module
framework, the activation gate, and the bridge land in later phases.
"""

from __future__ import annotations

from fastapi import FastAPI

from core import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="TMF Backend", version=__version__)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Process alive. Trivial (CORE.md §5)."""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()

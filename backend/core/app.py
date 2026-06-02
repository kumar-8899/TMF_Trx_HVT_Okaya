"""App factory + lifespan (CORE.md §5).

P2: boots the core services (config, diag, db, web) and exposes /healthz +
/readyz. The module framework + activation gate land in P3; the MQTT bridge
client and its readiness gate land in P4.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from core import __version__
from core.services.config import DEFAULT_CONFIG_DIR, ConfigService
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from core.services.web import install_web

DEFAULT_DB_PATH = Path(DEFAULT_CONFIG_DIR).parent / "data" / "tmf.sqlite"


def create_app(
    *,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. Boot core services (CORE.md §5 step 1).
        config = ConfigService(config_dir)
        app_cfg = config.load_app()
        station = app_cfg["station"]

        diag = Diagnostics(station, __version__)
        diag.start()

        db = Database(db_path, station=station, source_version=__version__)
        await db.connect()

        app.state.config = config
        app.state.app_config = app_cfg
        app.state.station = station
        app.state.diag = diag
        app.state.db = db

        web.add_ready_check("db", lambda: _check(db.connected))
        diag.info("core", "core services up", station=station, version=__version__)
        try:
            yield
        finally:
            # 5. Shutdown, reverse order (CORE.md §5 step 5).
            await db.close()
            diag.info("core", "core services down")
            diag.stop()

    app = FastAPI(title="TMF Backend", version=__version__, lifespan=lifespan)
    web = install_web(app)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Process alive. Trivial (CORE.md §5)."""
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    async def readyz():
        """Core services up (+ bridge online, added P4). CORE.md §5."""
        checks = app.state.ready_checks
        results = {name: await check() for name, check in checks.items()}
        ready = all(results.values())
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"ready": ready, "checks": results},
            status_code=200 if ready else 503,
        )

    return app


async def _check(value: bool) -> bool:
    return bool(value)


app = create_app()

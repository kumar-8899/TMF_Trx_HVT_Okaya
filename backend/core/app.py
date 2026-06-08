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
from core.framework.contract import Core
from core.framework.gate import ActivationResult, activate_modules
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry, discover
from core.services.auth_verify import TokenVerifier
from core.services.bridge import BridgeClient
from core.services.config import DEFAULT_CONFIG_DIR, ConfigService
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from core.services.licensing import Licensing
from core.services.web import install_web

DEFAULT_DB_PATH = Path(DEFAULT_CONFIG_DIR).parent / "data" / "tmf.sqlite"


def create_app(
    *,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
    enable_bridge: bool = True,
    broker_host: str = "127.0.0.1",
    broker_port: int = 1883,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. Boot core services (CORE.md §5 step 1).
        config = ConfigService(config_dir)
        app_cfg = config.load_app()
        station = app_cfg["station"]

        diag = Diagnostics(station, __version__)
        diag.start()

        drift = config.example_only_modules()
        if drift:
            diag.warning(
                "config",
                "live app.json is missing modules present in app.example.json; "
                "delete config/app.json to regenerate it",
                missing=drift,
            )

        db = Database(db_path, station=station, source_version=__version__)
        await db.connect()

        auth = TokenVerifier()

        # bridge.connect before the gate so modules needing it get it (CORE.md §5).
        bridge: BridgeClient | None = None
        if enable_bridge:
            bridge = BridgeClient(station, host=broker_host, port=broker_port, diag=diag)
            await bridge.connect()
            web.add_ready_check("bridge", lambda: _check(bridge.online))

        app.state.config = config
        app.state.app_config = app_cfg
        app.state.station = station
        app.state.diag = diag
        app.state.db = db
        app.state.bridge = bridge
        app.state.auth = auth  # the core.auth port (CORE.md §6.4); Auth module fills it

        web.add_ready_check("db", lambda: _check(db.connected))

        # 2-3. Activate + start modules through the gate (CORE.md §4-§5).
        core = Core(db=db, bridge=bridge, config=config, auth=auth, diag=diag, web=web, station=station)
        license = Licensing(config, diag).load_and_verify(app_cfg.get("license"))
        discover()
        result: ActivationResult = await activate_modules(
            core=core,
            registry=default_registry,
            manifests=ManifestLoader(),
            app_config=app_cfg,
            license=license,
            diag=diag,
        )
        app.state.core = core
        app.state.modules = result

        diag.info("core", "core services up", station=station, version=__version__)
        try:
            yield
        finally:
            # 5. Shutdown, reverse order (CORE.md §5 step 5).
            for mid, inst in reversed(list(result.active.items())):
                try:
                    await inst.stop()
                except Exception as exc:  # noqa: BLE001 — keep tearing down
                    diag.exception("core", "module stop failed", exc, module=mid)
            if bridge is not None:
                await bridge.disconnect()
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

    @app.get("/modules/status")
    async def modules_status() -> dict:
        """Loaded vs skipped + reason — debug surface + entitlement mirror (CORE.md §4)."""
        result: ActivationResult = app.state.modules
        return result.status_payload()

    return app


async def _check(value: bool) -> bool:
    return bool(value)


app = create_app()

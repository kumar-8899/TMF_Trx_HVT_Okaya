"""App factory + lifespan (CORE.md §5).

P2: boots the core services (config, diag, db, web) and exposes /healthz +
/readyz. The module framework + activation gate land in P3; the MQTT bridge
client and its readiness gate land in P4.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request

from core import __version__
from core.framework.contract import Core
from core.framework.gate import ActivationResult, activate_modules
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry, discover
from core.services.auth_verify import TokenVerifier
from core.services.bridge import BridgeClient
from core.services.interlock import InterlockPort
from core.services.config import DEFAULT_CONFIG_DIR, ConfigService
from core.services.db import Database
from core.services.diagnostics import BusDiagSink, Diagnostics
from core.services.licensing_keystation import build_licensing
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

        drift = config.config_drift()
        if any(drift.values()):
            diag.warning(
                "config",
                "live config is stale vs the examples — run `python -m tools.config_doctor "
                "--apply` to reconcile (non-destructive), then restart + re-login",
                missing_modules=drift["modules"], missing_roles=drift["roles"],
                missing_permissions=drift["permissions"], unlicensed_modules=drift["license_modules"],
            )

        db = Database(db_path, station=station, source_version=__version__)
        await db.connect()

        auth = TokenVerifier()
        interlock = InterlockPort()  # MES gate port; fail-open until an MES module fills it

        # bridge.connect before the gate so modules needing it get it (CORE.md §5).
        bridge: BridgeClient | None = None
        if enable_bridge:
            bridge = BridgeClient(station, host=broker_host, port=broker_port, diag=diag)
            await bridge.connect()
            web.add_ready_check("bridge", lambda: _check(bridge.online))
            # Mirror Python diag onto diag/# so the Debug Server can capture it
            # alongside LabVIEW's (DEBUG_SERVER.md §0/§3).
            diag.add_sink(BusDiagSink(bridge))

        app.state.config = config
        app.state.app_config = app_cfg
        app.state.station = station
        app.state.diag = diag
        app.state.db = db
        app.state.bridge = bridge
        app.state.auth = auth  # the core.auth port (CORE.md §6.4); Auth module fills it
        app.state.interlock = interlock

        web.add_ready_check("db", lambda: _check(db.connected))

        # 2-3. Activate + start modules through the gate (CORE.md §4-§5).
        licensing = build_licensing(app_cfg, config, diag)   # stub | keystation (config-selected)
        core = Core(db=db, bridge=bridge, config=config, auth=auth, diag=diag, web=web,
                    interlock=interlock, licensing=licensing, station=station)
        license = licensing.load_and_verify(app_cfg.get("license"))
        app.state.licensing = licensing   # activation endpoints + status surface

        from core.services.updates import UpdateService
        app.state.updates = UpdateService(db, licensing, diag, current_version=__version__,
                                          data_dir=DEFAULT_DB_PATH.parent)
        app.state.update_source = app_cfg.get("updates", {})   # {github_repo, github_token?}
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

    @app.get("/branding")
    async def branding() -> dict:
        """Public (pre-login) app identity — config `branding`, not source
        (TEMPLATE.md §1: an application rebrands via app.json, never code edits)."""
        cfg = getattr(app.state, "app_config", None) or {}
        out = {"name": "Test & Measurement", "short": "T",
               "product": "Test & Measurement Framework",
               "tagline": "Authorised access only. All sessions are encrypted.",
               "version": __version__}
        out.update(cfg.get("branding", {}) or {})
        return out

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

    # ---- licensing surface (secure distribution P1; Settings → License) ----
    from fastapi import Depends, HTTPException

    from core.services.security import require_permission

    async def _license_guard(request: Request):
        """SYSTEM.SETTINGS when the station is operational; open in ACTIVATION MODE
        (auth module not active because the station is unlicensed — the classic
        chicken-and-egg: you must be able to activate before anything can log in).
        A hostile lease is rejected by the core's signature verification, and the
        web edge is loopback-only."""
        modules = getattr(request.app.state, "modules", None)
        auth_active = bool(modules and "auth" in getattr(modules, "active", {}))
        if auth_active:
            await require_permission("SYSTEM.SETTINGS")(request)

    _LIC = [Depends(_license_guard)]

    @app.get("/license/status", dependencies=_LIC)
    async def license_status() -> dict:
        return app.state.licensing.status_payload()

    @app.post("/license/request", dependencies=_LIC)
    async def license_request(body: dict) -> dict:
        """Airgap step 1: emit a device-signed .ksreq (Keystation provider only)."""
        lic = app.state.licensing
        if not hasattr(lic, "make_request"):
            raise HTTPException(status_code=400, detail="provider does not support activation requests")
        try:
            return lic.make_request(body.get("product", "super_test_app"),
                                    body.get("runtime", "python_framework"))
        except Exception as exc:  # noqa: BLE001 — surface the SDK error honestly
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/license/activate", dependencies=_LIC)
    async def license_activate(body: dict) -> dict:
        """Ingest a .kslease bundle (path on the station). Restart applies the gate."""
        lic = app.state.licensing
        path = (body or {}).get("bundle_path", "")
        if not path:
            raise HTTPException(status_code=422, detail="bundle_path required")
        if not hasattr(lic, "activate"):
            raise HTTPException(status_code=400, detail="provider does not support activation")
        try:
            lic.activate(path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": True, "status": lic.status_payload(),
                "note": "restart the station to re-run the module gate with the new lease"}

    # ---- signed code updates (secure distribution P3; Settings → Updates) ---
    @app.post("/update/ingest", dependencies=_LIC)
    async def update_ingest(body: dict) -> dict:
        """Ingest a signed .ksupdate bundle (path on the station): verify + record."""
        path = (body or {}).get("bundle_path", "")
        if not path:
            raise HTTPException(status_code=422, detail="bundle_path required")
        try:
            return await app.state.updates.ingest(path)
        except Exception as exc:  # noqa: BLE001 — bad signature / unreadable bundle
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/update/offers", dependencies=_LIC)
    async def update_offers() -> dict:
        return {"current": app.state.updates.current(),
                "offers": await app.state.updates.list_offers(),
                "source": app.state.update_source.get("github_repo")}

    @app.post("/update/check", dependencies=_LIC)
    async def update_check() -> dict:
        """Pull + ingest the latest signed .ksupdate from the configured GitHub repo."""
        src = app.state.update_source
        repo = src.get("github_repo")
        if not repo:
            raise HTTPException(status_code=400, detail="no updates.github_repo configured")
        token = src.get("github_token") or os.environ.get("TMF_UPDATE_TOKEN")
        try:
            return await app.state.updates.check_github(repo, token)
        except Exception as exc:  # noqa: BLE001 — network / no-release / verify failure
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/update/apply/{release_id}", dependencies=_LIC)
    async def update_apply(release_id: str) -> dict:
        try:
            return await app.state.updates.apply(release_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/update/relaunch/{release_id}", dependencies=_LIC)
    async def update_relaunch(release_id: str) -> dict:
        """Write the launcher marker + exit with the RELAUNCH code (42) so the
        supervisor swaps the staged artifact and restarts. Requires the launcher —
        a bare backend just exits."""
        import threading
        try:
            marker = await app.state.updates.request_relaunch(release_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # exit AFTER the HTTP response is flushed, so the UI gets the ack.
        threading.Timer(0.6, lambda: os._exit(42)).start()
        return {"ok": True, "relaunching": marker.get("version"),
                "note": "station is relaunching to apply the update"}

    return app


async def _check(value: bool) -> bool:
    return bool(value)


app = create_app()

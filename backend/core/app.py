"""App factory + lifespan (CORE.md §5).

P2: boots the core services (config, diag, db, web) and exposes /healthz +
/readyz. The module framework + activation gate land in P3; the MQTT bridge
client and its readiness gate land in P4.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request

from core import __version__, app_version
from core.services.security import require_role
from core.framework.contract import Core
from core.framework.gate import ActivationResult, activate_modules
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry, discover
from core.services.auth_verify import TokenVerifier
from core.services.bridge import MultiStationBridge
from core.services.interlock import InterlockPort
from core.services.config import ConfigService, resolve_state_dirs
from core.services.db import Database
from core.services.diagnostics import LEVELS, BusDiagSink, Diagnostics
from core.services.licensing_keystation import build_licensing
from core.services.spa import install_spa, resolve_frontend_dist
from core.services.web import install_web

# Live config + data live OUTSIDE a swappable run.dist when frozen (TMF_STATE_DIR); the
# read-only *.example.json stay bundled. Source/tests = today's backend/ layout.
_LIVE_CONFIG_DIR, _EXAMPLES_DIR, _DATA_DIR = resolve_state_dirs()
DEFAULT_CONFIG_DIR = _LIVE_CONFIG_DIR
DEFAULT_DB_PATH = _DATA_DIR / "tmf.sqlite"


def create_app(
    *,
    config_dir: Path | str = _LIVE_CONFIG_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
    enable_bridge: bool = True,
    broker_host: str = "127.0.0.1",
    broker_port: int = 1883,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. Boot core services (CORE.md §5 step 1). Bundled examples only when using the
        # default (possibly external) config dir; a caller-supplied dir is self-contained.
        examples = _EXAMPLES_DIR if str(config_dir) == str(_LIVE_CONFIG_DIR) else None
        config = ConfigService(config_dir, examples_dir=examples)
        app_cfg = config.load_app()
        requested_stations = list(app_cfg["stations"])
        station = requested_stations[0]   # DEPRECATED primary; per-station bridge lands in M2

        diag = Diagnostics(station, __version__)
        diag.start()
        if app_cfg.get("stations_migrated"):
            diag.warning("core", "app.json uses the deprecated singular `station` key — "
                         "migrate to `stations: [...]` (MULTI_STATION.md §1)", station=station)

        drift = config.config_drift()
        if any(drift.values()):
            diag.warning(
                "config",
                "live config is stale vs the examples — run `python -m tools.config_doctor "
                "--apply` to reconcile (non-destructive), then restart + re-login",
                missing_modules=drift["modules"], missing_roles=drift["roles"],
                missing_permissions=drift["permissions"], unlicensed_modules=drift["license_modules"],
            )

        # 2. License first so the station cap is known before the bridge connects.
        licensing = build_licensing(app_cfg, config, diag)   # stub | keystation (config-selected)
        license = licensing.load_and_verify(app_cfg.get("license"))

        # License station cap (MULTI_STATION.md §1): take the first `max_stations`
        # entries, record each refusal in /modules/status — fail-closed, do not refuse
        # to boot (CORE.md §4). None = uncapped.
        cap = license.max_stations()
        if cap is not None and len(requested_stations) > cap:
            stations = requested_stations[:cap]
            station_refusals = requested_stations[cap:]
            diag.warning("core", "stations capped by license max_stations",
                         max_stations=cap, refused=station_refusals)
        else:
            stations, station_refusals = requested_stations, []

        db = Database(db_path, station=station, source_version=__version__)
        await db.connect()

        auth = TokenVerifier()
        interlock = InterlockPort()  # MES gate port; fail-open until an MES module fills it

        # bridge.connect before the gate so modules needing it get it (CORE.md §5).
        # One MQTT connection per licensed station (MULTI_STATION.md §2).
        bridge: MultiStationBridge | None = None
        if enable_bridge:
            bridge = MultiStationBridge(stations, host=broker_host, port=broker_port, diag=diag)
            await bridge.connect()
            web.add_ready_check("bridge", lambda: _check(bridge.any_link_online))
            # Mirror Python diag onto diag/# so the Debug Server can capture it
            # alongside LabVIEW's (DEBUG_SERVER.md §0/§3).
            diag.add_sink(BusDiagSink(bridge))

        app.state.config = config
        app.state.app_config = app_cfg
        app.state.station = station
        app.state.stations = stations
        app.state.station_refusals = station_refusals
        app.state.max_stations = cap
        app.state.diag = diag
        app.state.db = db
        app.state.bridge = bridge
        app.state.auth = auth  # the core.auth port (CORE.md §6.4); Auth module fills it
        app.state.interlock = interlock
        app.state.licensing = licensing   # activation endpoints + status surface

        web.add_ready_check("db", lambda: _check(db.connected))

        # Python controller: when selected, the app owns its lifecycle (starts it with the
        # app, stops it on shutdown). LabVIEW (default) is external — nothing spawned.
        controller_cfg = app_cfg.get("controller") or {}
        app.state.controller = None
        if controller_cfg.get("kind") == "python":
            from core.services.controller_supervisor import ControllerSupervisor
            # The Instruments page (config module `instrument` records) is the single
            # source of instrument instances for the WHOLE app — backend variable engine
            # AND the controller. Unconfigured ⇒ the controller starts with none, even in
            # simulation; the operator adds them in Config → Instruments and restarts.
            try:
                _rows = await db.repo.query("instrument")
            except Exception:  # noqa: BLE001 — fresh station, no records yet
                _rows = []
            py_instruments = [
                {"id": r["data"]["id"], "library": r["data"]["library"],
                 "params": r["data"].get("params", {}),
                 "simulated": r["data"].get("simulated", False),
                 "stations": r["data"].get("stations") or list(stations)}
                for r in _rows
                if r["data"].get("owner") == "python"
                and r["data"].get("enabled", True) and r["data"].get("library")]
            # Simulation is per-instrument only (Instruments page `simulated` toggle).
            # The old app-level controller.simulation knob is deprecated and ignored.
            if controller_cfg.get("simulation"):
                diag.warning("controller", "app.json controller.simulation is deprecated and "
                             "ignored — simulation is set per instrument on the Instruments page")
            sup = ControllerSupervisor(
                stations=stations, broker_host=broker_host, broker_port=broker_port,
                diag=diag,
                data_dir=DEFAULT_DB_PATH.parent, repo_root=Path(__file__).resolve().parents[2],
                config_file=controller_cfg.get("config_file"),
                instruments=py_instruments)
            sup.start()
            app.state.controller = sup

        # 2-3. Activate + start modules through the gate (CORE.md §4-§5).
        core = Core(db=db, bridge=bridge, config=config, auth=auth, diag=diag, web=web,
                    interlock=interlock, licensing=licensing, stations=stations, station=station)
        # The LICENSED unit's identity. For the framework repo this is the framework
        # itself (dev); a derived customer app sets licensing.product to its own
        # app-track slug (SECURE_DISTRIBUTION.md; TEMPLATE.md two-tier model).
        _lic_cfg = app_cfg.get("licensing") or {}
        app.state.license_product = _lic_cfg.get("product") or "super_test_app"
        app.state.license_runtime = _lic_cfg.get("runtime") or "python_framework"

        from core.services.updates import UpdateService
        app.state.updates = UpdateService(db, licensing, diag, current_version=__version__,
                                          current_app_version=app_version(),
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
        fe = getattr(app.state, "frontend_dist", None)
        if fe is not None:
            diag.info("core", "serving bundled UI from this edge (single-origin)", dir=str(fe))
        try:
            yield
        finally:
            # 5. Shutdown, reverse order (CORE.md §5 step 5).
            for mid, inst in reversed(list(result.active.items())):
                try:
                    await inst.stop()
                except Exception as exc:  # noqa: BLE001 — keep tearing down
                    diag.exception("core", "module stop failed", exc, module=mid)
            sup = getattr(app.state, "controller", None)
            if sup is not None:
                sup.stop()
            if bridge is not None:
                await bridge.disconnect()
            await db.close()
            diag.info("core", "core services down")
            diag.stop()

    app = FastAPI(title="TMF Backend", version=__version__, lifespan=lifespan)
    web = install_web(app)

    # Single-origin production: when a built SPA is present, serve it from this edge
    # so the one-click launcher only opens http://127.0.0.1:8000. A pure-Vite dev
    # checkout has no bundle → API-only, unchanged (core/services/spa.py).
    frontend_dist = resolve_frontend_dist()
    app.state.frontend_dist = frontend_dist
    if frontend_dist is not None:
        install_spa(app, frontend_dist)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Process alive. Trivial (CORE.md §5)."""
        return {"status": "ok", "version": __version__}

    # logo_client / logo_exeliq are data: URLs (small PNG/SVG) uploaded from the Branding
    # page — client logo shows top-left, Exeliq logo top-right (issue #7).
    _BRAND_FIELDS = ("name", "short", "product", "tagline", "logo_client", "logo_exeliq")

    async def _branding_payload() -> dict:
        """Defaults ∪ app.json `branding` ∪ the DB override (Setup wizard edit).
        DB wins so a station rebrands live, without editing app.json (TEMPLATE.md §1:
        an application rebrands via config, never code edits)."""
        cfg = getattr(app.state, "app_config", None) or {}
        out = {"name": "Test & Measurement", "short": "T",
               "product": "Test & Measurement Framework",
               "tagline": "Authorised access only. All sessions are encrypted.",
               "logo_client": "", "logo_exeliq": "",
               "version": __version__, "framework_version": __version__,
               "app_version": app_version()}
        out.update(cfg.get("branding", {}) or {})
        # Controller kind rides along so the UI can adapt (e.g. the Instruments page
        # hides the LabVIEW-owned transport path on a Python-controller app).
        out["controller"] = (cfg.get("controller") or {}).get("kind", "labview")
        db = getattr(app.state, "db", None)
        if db is not None:
            try:
                rec = await db.repo.get("branding", "branding")
            except Exception:  # noqa: BLE001 — no DB yet: static branding only
                rec = None
            if rec:
                out.update({k: v for k, v in (rec["data"] or {}).items() if k in _BRAND_FIELDS})
        return out

    @app.get("/branding")
    async def branding() -> dict:
        """Public (pre-login) app identity."""
        return await _branding_payload()

    @app.put("/branding", dependencies=[Depends(require_role("super_admin"))])
    async def set_branding(body: dict) -> dict:
        """Persist the app identity as a DB override (Setup wizard / Branding form).
        Applies live — clients re-fetch /branding."""
        clean = {k: str(body.get(k, "")).strip() for k in _BRAND_FIELDS if body.get(k) is not None}
        if not clean.get("name"):
            raise HTTPException(status_code=400, detail="name is required")
        await app.state.db.repo.put("branding", clean, id="branding", summary=clean["name"])
        app.state.diag.info("core", "branding updated", name=clean["name"])
        return await _branding_payload()

    @app.get("/readyz")
    async def readyz():
        """Core up AND at least one station's bridge link online (MULTI_STATION.md §3).
        Body carries per-station link state so an operator sees which socket is missing;
        a single unplugged bench does not take the app down."""
        checks = app.state.ready_checks
        results = {name: await check() for name, check in checks.items()}
        ready = all(results.values())
        br = getattr(app.state, "bridge", None)
        stations = getattr(app.state, "stations", [])
        station_links = br.link_map() if br is not None else {st: "offline" for st in stations}
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"ready": ready, "checks": results, "stations": station_links,
             "station_refusals": getattr(app.state, "station_refusals", [])},
            status_code=200 if ready else 503,
        )

    @app.get("/modules/status")
    async def modules_status() -> dict:
        """Loaded vs skipped + reason — debug surface + entitlement mirror (CORE.md §4).
        Carries the licensed station list + any license-refused stations so the frontend
        learns the socket count from one place (MULTI_STATION.md §6)."""
        result: ActivationResult = app.state.modules
        return {**result.status_payload(),
                "stations": getattr(app.state, "stations", []),
                "station_refusals": getattr(app.state, "station_refusals", [])}

    # ---- station configuration (Settings → Station; SYSTEM.SETTINGS) --------
    from core.services.security import require_permission
    _SETTINGS = [Depends(require_permission("SYSTEM.SETTINGS"))]

    def _running_controller_kind() -> str:
        return "python" if getattr(app.state, "controller", None) is not None else "labview"

    def _station_config_payload() -> dict:
        cfg = app.state.app_config
        configured = list(cfg.get("stations") or [])
        controller = cfg.get("controller") or {}
        kind = controller.get("kind", "labview")
        running = list(app.state.stations)
        restart = configured != running or kind != _running_controller_kind()
        return {
            "station_count": len(configured),
            "configured_stations": configured,
            "running_stations": running,
            "max_stations": app.state.max_stations,          # None = uncapped
            "controller": {"kind": kind},
            "restart_required": restart,
        }

    @app.get("/system/station-config", dependencies=_SETTINGS)
    async def get_station_config() -> dict:
        return _station_config_payload()

    @app.put("/system/station-config", dependencies=_SETTINGS)
    async def set_station_config(body: dict) -> dict:
        """Edit boot config (socket count + controller). Written to app.json; applied on
        the next restart. Socket count is st1..stN, capped at the licensed max_stations."""
        patch: dict = {}
        count = body.get("station_count")
        if count is not None:
            try:
                count = int(count)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="station_count must be an integer")
            if count < 1:
                raise HTTPException(status_code=422, detail="station_count must be at least 1")
            cap = app.state.max_stations
            if cap is not None and count > cap:
                raise HTTPException(status_code=422,
                                    detail=f"station_count {count} exceeds licensed max_stations {cap}")
            patch["stations"] = [f"st{i}" for i in range(1, count + 1)]
        kind = body.get("controller_kind")
        if kind is not None:
            if kind not in ("labview", "python"):
                raise HTTPException(status_code=422, detail="controller_kind must be 'labview' or 'python'")
            controller = dict(app.state.app_config.get("controller") or {})
            controller["kind"] = kind
            # simulation is per-instrument (Instruments page) — the old app-level knob
            # is dropped from the config when this section is saved.
            controller.pop("simulation", None)
            patch["controller"] = controller
        if not patch:
            raise HTTPException(status_code=422, detail="nothing to update")
        try:
            app.state.app_config = app.state.config.update_app(patch)
        except Exception as exc:  # noqa: BLE001 — surface a bad write as 400, not 500
            raise HTTPException(status_code=400, detail=f"config update failed: {exc}")
        app.state.diag.info("core", "station config updated", patch=patch)
        return {"ok": True, **_station_config_payload()}

    # ---- live diagnostics verbosity (REMOTE_DEBUG.md §3.5) -----------------
    # The Debug Server sidecar relays here over HTTP (never the cmd/ tree). Setting a
    # subsystem's level gates emission at the source, above the logs module's
    # persistence filter — effective immediately, not persisted across restart.
    @app.get("/diag/level", dependencies=_SETTINGS)
    async def get_diag_level() -> dict:
        return app.state.diag.get_levels()

    @app.put("/diag/level", dependencies=_SETTINGS)
    async def set_diag_level(body: dict) -> dict:
        subsystem = (body or {}).get("subsystem")
        level = (body or {}).get("level")
        if not subsystem or level not in LEVELS:
            raise HTTPException(status_code=422,
                                detail=f"subsystem required and level one of {list(LEVELS)}")
        app.state.diag.set_level(subsystem, level)
        app.state.diag.info("core", "diag level set", target=subsystem, level=level)
        return {"applied": {subsystem: level}, **app.state.diag.get_levels()}

    # ---- remote debugging on/off (Settings → Remote debugging) -------------
    # The flight-recorder sidecar is supervised by station.py when app.json debug.enabled
    # is true; toggling here writes app.json and is applied on the next relaunch. The
    # token is write-only (never returned). Live status is a best-effort probe of the
    # sidecar's own /debug/health.
    _LOOPBACK = {"127.0.0.1", "::1", "localhost"}

    async def _probe_debug(dbg: dict) -> dict:
        host = dbg.get("bind_host") or "127.0.0.1"
        port = int(dbg.get("port") or 8001)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=1.5) as c:
                r = await c.get(f"http://{host}:{port}/debug/health")
            return {"running": r.status_code == 200, "health": r.json() if r.status_code == 200 else None}
        except Exception:  # noqa: BLE001 — sidecar not up / unreachable is normal
            return {"running": False, "health": None}

    def _debug_payload(dbg: dict, status: dict, restart: bool = False) -> dict:
        host = dbg.get("bind_host") or "127.0.0.1"
        return {
            "enabled": bool(dbg.get("enabled")),
            "bind_host": host,
            "port": int(dbg.get("port") or 8001),
            "remote": host not in _LOOPBACK,
            "has_token": bool(dbg.get("token")),
            "rolling_enabled": bool((dbg.get("rolling") or {}).get("enabled", True)),
            "restart_required": restart,
            **status,
        }

    @app.get("/system/debug-config", dependencies=_SETTINGS)
    async def get_debug_config() -> dict:
        dbg = dict(app.state.app_config.get("debug") or {})
        return _debug_payload(dbg, await _probe_debug(dbg))

    @app.put("/system/debug-config", dependencies=_SETTINGS)
    async def set_debug_config(body: dict) -> dict:
        dbg = dict(app.state.app_config.get("debug") or {})
        if "enabled" in body:
            dbg["enabled"] = bool(body["enabled"])
        if "bind_host" in body:
            dbg["bind_host"] = (body["bind_host"] or "127.0.0.1").strip()
        if "token" in body:                       # write-only; "" clears it
            dbg["token"] = body["token"] or None
        if "rolling_enabled" in body:
            roll = dict(dbg.get("rolling") or {})
            roll["enabled"] = bool(body["rolling_enabled"])
            dbg["rolling"] = roll
        # mirror the sidecar's own start-up guard so the UI can't save an unsafe combo
        host = dbg.get("bind_host") or "127.0.0.1"
        if host == "0.0.0.0":  # noqa: S104 — the value we forbid
            raise HTTPException(status_code=422, detail="bind_host must be an explicit interface, not 0.0.0.0")
        if host not in _LOOPBACK and not dbg.get("token"):
            raise HTTPException(status_code=422, detail="a token is required to expose remote debugging on a non-loopback address")
        try:
            app.state.app_config = app.state.config.update_app({"debug": dbg})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"config update failed: {exc}") from exc
        app.state.diag.info("core", "debug config updated", enabled=dbg.get("enabled"), remote=host not in _LOOPBACK)
        return {"ok": True, **_debug_payload(dbg, await _probe_debug(dbg), restart=True)}

    @app.post("/system/relaunch", dependencies=_SETTINGS)
    async def system_relaunch() -> dict:
        """Relaunch the station to apply a config change (exit 42 → the launcher restarts).
        os._exit skips lifespan cleanup, so stop the child controller here first."""
        sup = getattr(app.state, "controller", None)
        if sup is not None:
            sup.stop()
        app.state.diag.info("core", "station relaunch requested (config change)")
        threading.Timer(0.6, lambda: os._exit(42)).start()
        return {"ok": True, "relaunching": True, "note": "station is relaunching to apply configuration"}

    @app.post("/system/shutdown", dependencies=_SETTINGS)
    async def system_shutdown() -> dict:
        """Exit the station SAFELY. Raises SIGINT to trigger the full lifespan shutdown —
        modules stop, the Python controller is gracefully stopped (every instrument driven
        to safe state), the bridge goes offline, the DB is closed — then the process exits 0,
        so the launcher does NOT restart it (that is what distinguishes exit from relaunch).
        A watchdog hard-exits if a graceful shutdown stalls."""
        app.state.diag.info("core", "station shutdown requested")

        def _graceful():
            try:
                signal.raise_signal(signal.SIGINT)     # main-thread signal → uvicorn graceful exit
            except Exception:  # noqa: BLE001 — no signal support → hard exit
                os._exit(0)

        asyncio.get_event_loop().call_later(0.5, _graceful)
        threading.Timer(12.0, lambda: os._exit(0)).start()   # fallback if shutdown stalls
        return {"ok": True, "shutting_down": True, "note": "station is exiting"}

    # ---- licensing surface (secure distribution P1; Settings → License) ----
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
        return {**app.state.licensing.status_payload(),
                "product": app.state.license_product, "runtime": app.state.license_runtime}

    @app.post("/license/request", dependencies=_LIC)
    async def license_request(body: dict) -> dict:
        """Airgap step 1: emit a device-signed .ksreq for THIS deployment's product
        (config-driven; a customer app requests its own app-track slug, not the
        framework's)."""
        lic = app.state.licensing
        if not hasattr(lic, "make_request"):
            raise HTTPException(status_code=400, detail="provider does not support activation requests")
        product = (body or {}).get("product") or app.state.license_product
        runtime = (body or {}).get("runtime") or app.state.license_runtime
        try:
            return lic.make_request(product, runtime)
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

    def _update_repo_token() -> tuple[str, str | None, str]:
        src = app.state.update_source
        repo = src.get("github_repo")
        if not repo:
            raise HTTPException(status_code=400, detail="no updates.github_repo configured")
        token = src.get("github_token") or os.environ.get("TMF_UPDATE_TOKEN")
        return repo, token, src.get("channel", "stable")

    @app.post("/update/check", dependencies=_LIC)
    async def update_check() -> dict:
        """Discovery — NOTIFY ONLY. Polls GitHub, downloads nothing (UPDATES.md item 5)."""
        repo, token, channel = _update_repo_token()
        return await app.state.updates.check(repo, token, channel=channel)

    @app.post("/update/download", dependencies=_LIC)
    async def update_download() -> dict:
        """Fetch the latest .ksupdate, verify + offer (item 6). Idempotent on bundle hash."""
        from core.services.updates import AmcRequired
        repo, token, channel = _update_repo_token()
        try:
            return await app.state.updates.download(repo, token, channel=channel)
        except AmcRequired as exc:
            raise HTTPException(status_code=402, detail=str(exc)) from exc   # UPDATES.md §8.5
        except Exception as exc:  # noqa: BLE001 — network / no-release / verify failure
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/update/apply/{release_id}", dependencies=_LIC)
    async def update_apply(release_id: str) -> dict:
        # Never swap a binary mid-test (UPDATES.md item 8): refuse while any run is active.
        runs = getattr(app.state, "modules", None)
        runs = runs.active.get("runs") if runs is not None else None
        if runs is not None and getattr(runs, "_active", None):
            raise HTTPException(status_code=409,
                                detail=f"a run is active ({runs._active}) — cannot apply an update mid-test")
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

    @app.get("/update/status", dependencies=_LIC)
    async def update_status() -> dict:
        return await app.state.updates.status()

    @app.post("/update/rollback", dependencies=_LIC)
    async def update_rollback(body: dict) -> dict:
        """Roll back to last_known_good (default) or a specific backup id. Refused mid-run."""
        runs = getattr(app.state, "modules", None)
        runs = runs.active.get("runs") if runs is not None else None
        if runs is not None and getattr(runs, "_active", None):
            raise HTTPException(status_code=409, detail="a run is active — cannot roll back mid-test")
        import threading
        target = (body or {}).get("target", "last_known_good")
        try:
            marker = await app.state.updates.rollback(target)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        threading.Timer(0.6, lambda: os._exit(42)).start()
        return {"ok": True, "rolling_back": marker.get("rollback"),
                "note": "station is relaunching to roll back"}

    return app


async def _check(value: bool) -> bool:
    return bool(value)


app = create_app()

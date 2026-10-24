"""The Debug Tool's web app: MCP endpoint + token gate + the operator's control API (docs/DEBUG_TOOL.md).

Three audiences, three doors:

  /mcp, /files/<id>, /debug/*   Claude Code on the developer's machine. Needs `Authorization: Bearer <token>` AND an active
                                sharing session (consent.SharingState). Every request is written to the access log.
  /operator/*                   the person at the client PC (the UI). Loopback / the server's own address only AND the
                                per-process `X-Operator-Key`. This is the ONLY door that can approve an action: the MCP
                                token can never approve its own requests.
  /healthz                      unauthenticated liveness (no data) for the launcher / verify script.
"""

from __future__ import annotations

import contextlib
import getpass
import hmac
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from debug_tool import VERSION
from debug_tool.consent import AccessLog, ApprovalQueue, ConsentError, SharingState
from debug_tool.engine import Engine, EngineConfig
from debug_tool.mcp_server import Host, build_mcp

PROTECTED = ("/mcp", "/files/", "/debug/")
LOCAL_HOSTS = ("127.0.0.1", "::1", "localhost")


def problem(status: int, title: str, detail: str) -> JSONResponse:
    """RFC-7807 body - the same shape the rest of the platform uses."""
    return JSONResponse({"type": "about:blank", "title": title, "status": status, "detail": detail}, status_code=status,
                        media_type="application/problem+json")


def _is_protected(path: str) -> bool:
    return path == "/mcp" or any(path.startswith(p) for p in PROTECTED)


class GateMiddleware:
    """Pure-ASGI (no BaseHTTPMiddleware: it breaks streaming responses) gate for the remote door."""

    def __init__(self, app: ASGIApp, *, sharing: SharingState, log: AccessLog) -> None:
        self.app, self.sharing, self.log = app, sharing, log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_protected(scope["path"]):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        remote = (scope.get("client") or ("?", 0))[0]
        path = scope["path"]
        if not self.sharing.active():
            self.log.write(event="http_refused", path=path, remote=remote, reason="sharing_off")
            await problem(403, "Sharing is off", "the operator has not turned sharing on at the client PC (or it expired)")(scope, receive, send)
            return
        if not self.sharing.check_token(token):
            self.log.write(event="http_refused", path=path, remote=remote, reason="bad_token")
            await problem(401, "Invalid token", "missing or wrong bearer token")(scope, receive, send)
            return
        self.sharing.touch(remote)
        status: dict = {}

        async def spy(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, spy)
        finally:
            self.log.write(event="http", method=scope.get("method"), path=path, remote=remote, status=status.get("code"))


@dataclass
class Runtime:
    engine: Engine
    sharing: SharingState
    approvals: ApprovalQueue
    log: AccessLog
    operator_key: str


def create_runtime(cfg: EngineConfig, *, approval_timeout_s: float | None = None, **engine_kw) -> Runtime:
    log = AccessLog(cfg.data_dir / "access.jsonl")
    kw = {} if approval_timeout_s is None else {"timeout_s": approval_timeout_s}
    return Runtime(Engine(cfg, **engine_kw), SharingState(log=log), ApprovalQueue(log=log, **kw), log, secrets.token_urlsafe(24))


_NAME_OK = re.compile(r"[^a-z0-9-]+")


def _bench_name(engine: Engine, requested: str | None) -> str:
    base = requested or ("bench-" + str(engine.app.as_dict().get("product") or (engine.app.stations() or ["st1"])[0]))
    return _NAME_OK.sub("-", base.lower()).strip("-") or "bench"


def build_app(rt: Runtime, *, bind_host: str = "127.0.0.1", port: int = 8010, heartbeat_s: float = 10.0,
              extra_tools: list[Callable[[Host], None]] | None = None, manage_engine: bool = True):
    if bind_host in ("0.0.0.0", "::", ""):
        raise ValueError("bind to one specific address (127.0.0.1, or the PC's VPN/LAN address) - never all interfaces")
    engine, sharing, approvals, log = rt.engine, rt.sharing, rt.approvals, rt.log
    mcp, _host = build_mcp(engine, sharing, approvals, log, host=bind_host, port=port, heartbeat_s=heartbeat_s, extra=extra_tools)
    mcp_app = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if manage_engine:
            await engine.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            approvals.deny_all("shutdown")
            sharing.stop("shutdown")
            if manage_engine:
                await engine.stop()

    app = FastAPI(title="TMF Debug Tool", version=VERSION, lifespan=lifespan)
    app.state.runtime = rt
    app.state.mcp = mcp
    app.router.routes.extend(mcp_app.routes)                      # exactly /mcp - no trailing-slash redirect
    app.add_middleware(GateMiddleware, sharing=sharing, log=log)

    local = set(LOCAL_HOSTS) | {bind_host}

    async def require_operator(request: Request, x_operator_key: str | None = Header(default=None)) -> None:
        host = request.client.host if request.client else ""
        if host not in local:
            raise HTTPException(403, "operator endpoints answer only on the client PC itself")
        if not x_operator_key or not hmac.compare_digest(x_operator_key, rt.operator_key):
            raise HTTPException(401, "missing or wrong operator key")

    op = [Depends(require_operator)]

    # ------------------------------------------------------------------ open
    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "tool": "tmf-debug-tool", "version": VERSION}

    # ------------------------------------------------------------------ remote (token + sharing)
    @app.get("/debug/health")
    def debug_health() -> dict:
        return engine.health()

    @app.get("/files/{download_id}")
    def files(download_id: str):
        path = engine.downloads.get(download_id)
        if path is None or not Path(path).is_file():
            raise HTTPException(404, "no such download (they exist only for exports a human approved)")
        log.write(event="download", id=download_id, file=Path(path).name)
        return FileResponse(path, filename=Path(path).name)

    # ------------------------------------------------------------------ operator
    @app.get("/operator/status", dependencies=op)
    def operator_status() -> dict:
        return {"tool": "tmf-debug-tool", "version": VERSION, "bind": f"{bind_host}:{port}", "mcp_url": f"http://{bind_host}:{port}/mcp",
                "sharing": sharing.status(), "pending_approvals": len(approvals.pending()), "health": engine.health()}

    @app.post("/operator/sharing/start", dependencies=op)
    def sharing_start(body: dict | None = None) -> dict:
        body = body or {}
        try:
            token = sharing.start(float(body.get("hours", 4.0)), allow_during_run=bool(body.get("allow_during_run", False)))
        except (ConsentError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        name = _bench_name(engine, body.get("name"))
        url = f"http://{bind_host}:{port}/mcp"
        return {"token": token, "fingerprint": sharing.fingerprint(), "mcp_url": url, "expires_in_s": sharing.status()["seconds_left"],
                "claude_command": f'claude mcp add --transport http {name} {url} --header "Authorization: Bearer {token}"',
                "mcp_json": {"mcpServers": {name: {"type": "http", "url": url,
                                                  "headers": {"Authorization": "Bearer ${TMF_DEBUG_TOKEN}",
                                                              "X-Core-Token": "${TMF_CORE_TOKEN}"}}}},
                "note": "the token is shown once and is never stored; X-Core-Token (a core login with SYSTEM.SETTINGS) is only "
                        "needed for bench_level_get/bench_level_set"}

    @app.post("/operator/sharing/stop", dependencies=op)
    def sharing_stop() -> dict:
        sharing.stop("operator")
        return {"stopped": True, "denied_pending": approvals.deny_all("stopped")}

    @app.get("/operator/approvals", dependencies=op)
    def approvals_list() -> dict:
        return {"pending": approvals.pending(), "history": approvals.history()}

    @app.post("/operator/approvals/{rid}", dependencies=op)
    def approvals_decide(rid: str, body: dict) -> dict:
        approve = bool(body.get("approve"))
        ok = approvals.decide(rid, approve, by=getpass.getuser(), extra={"allow_during_run": bool(body.get("allow_during_run", False))})
        if not ok:
            raise HTTPException(404, "that request is no longer pending (it timed out, was decided, or sharing was stopped)")
        return {"id": rid, "decision": "approved" if approve else "denied"}

    @app.get("/operator/access", dependencies=op)
    def access(n: int = 50) -> dict:
        return {"entries": log.tail(max(1, min(n, 500)))}

    @app.get("/operator/live", dependencies=op)
    def live(n: int = 100) -> dict:
        from debug_tool.engine import normalise
        recent = engine.ingestor.ring.query(limit=max(1, min(n, 500))) if engine.ingestor else []
        return {"live": engine.health()["live"], "events": [normalise(r) for r in recent]}

    # -- the operator's own actions: the person at the PC is the human in the loop, so these need no approval card ------------
    @app.post("/operator/collect", dependencies=op)
    async def operator_collect(body: dict | None = None) -> dict:
        body = body or {}
        desktop = Path.home() / "Desktop"
        try:
            res = await engine.export_bundle(rows=max(100, min(int(body.get("rows", 5000)), 50_000)),
                                             integrity=bool(body.get("integrity", True)),
                                             out_dir=desktop if desktop.is_dir() else engine.cfg.data_dir / "bundles", register=False)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        log.write(event="operator_collect", file=res["path"], by=getpass.getuser())
        return res

    @app.get("/operator/scripts", dependencies=op)
    def scripts_history() -> dict:
        return {"busy": engine.scripts.busy, "history": engine.scripts.history(50)}

    @app.post("/operator/scripts/run", dependencies=op)
    async def scripts_run(body: dict) -> dict:
        from debug_tool.scripts import ScriptBusy, ScriptError
        from debug_tool.pyenv import PythonUnavailable
        if engine.run_active() and not body.get("allow_during_run"):
            raise HTTPException(409, "a test run is in progress - tick 'allow during a test' if this script cannot disturb it")
        try:
            res = await engine.scripts.run(str(body.get("interpreter", "")), str(body.get("script", "")),
                                           timeout_s=body.get("timeout_s"), args=body.get("args"), approved_by=getpass.getuser())
        except ScriptBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ScriptError, PythonUnavailable) as exc:
            raise HTTPException(400, str(exc)) from exc
        log.write(event="operator_script", sha256=res["sha256"], interpreter=res["interpreter"], exit_code=res["exit_code"],
                  by=getpass.getuser())
        return res

    @app.get("/operator/python", dependencies=op)
    async def python_status() -> dict:
        import asyncio
        return await asyncio.to_thread(engine.pyenv.status)

    @app.post("/operator/python/extract", dependencies=op)
    async def python_extract() -> dict:
        import asyncio
        from debug_tool.pyenv import PythonUnavailable
        try:
            return {"resolved": await asyncio.to_thread(engine.pyenv.resolve), "status": await asyncio.to_thread(engine.pyenv.status)}
        except PythonUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/operator/analyze", dependencies=op)
    async def analyze_path(body: dict) -> dict:
        import asyncio
        from tmf_debug.bundle import BundleError
        try:
            return await asyncio.to_thread(engine.analyze_bundle, str(body.get("path", "")).strip().strip('"'))
        except BundleError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/operator/analyze-upload", dependencies=op)
    async def analyze_upload(request: Request, name: str = "bundle") -> dict:
        import asyncio
        from tmf_debug.bundle import BundleError
        raw = await request.body()
        if not raw:
            raise HTTPException(400, "empty upload")
        up = engine.cfg.data_dir / "uploads"
        up.mkdir(parents=True, exist_ok=True)
        dest = up / f"{_NAME_OK.sub('-', name.lower()).strip('-') or 'bundle'}-{secrets.token_hex(3)}.zip"
        dest.write_bytes(raw)
        try:
            return await asyncio.to_thread(engine.analyze_bundle, dest)
        except BundleError as exc:
            raise HTTPException(400, str(exc)) from exc

    # -- the operator's page ------------------------------------------------------------------------------------------------
    ui_file = Path(__file__).resolve().parent / "ui" / "index.html"

    @app.get("/", include_in_schema=False)
    def operator_ui(request: Request):
        from fastapi.responses import HTMLResponse
        host = request.client.host if request.client else ""
        if host not in local:
            raise HTTPException(403, "the operator page opens only on the client PC itself")
        html = ui_file.read_text(encoding="utf-8").replace("__OPERATOR_KEY__", rt.operator_key).replace("__VERSION__", VERSION)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return app

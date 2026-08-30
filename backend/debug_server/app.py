"""Debug Server REST + WS surface (DEBUG_SERVER.md §8). Its own FastAPI app on its
own port — not mounted under the core web shell."""

from __future__ import annotations

from pathlib import Path

import json

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from debug_server.auth import TokenChecker
from debug_server.config import DebugConfig
from debug_server.ingest import Ingestor

_UI = Path(__file__).resolve().parent / "ui" / "index.html"


def build_app(ingestor: Ingestor, config: DebugConfig, checker: TokenChecker) -> FastAPI:
    app = FastAPI(title="TMF Debug Server", version="1.0.0")
    app.state.ingestor = ingestor

    async def require_token(authorization: str | None = Header(default=None)) -> None:
        token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
        if not await checker.check(token):
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    auth = [Depends(require_token)]

    @app.get("/debug/events", dependencies=auth)
    def events(since: int | None = None, level: str | None = None, subsystem: str | None = None,
               topic: str | None = None, trace: str | None = None, kind: str | None = None,
               text: str | None = None, limit: int = 500) -> list[dict]:
        recs = ingestor.ring.query(since=since, level=level, subsystem=subsystem, topic=topic,
                                   trace=trace, kind=kind, text=text, limit=limit)
        return [r.to_dict() for r in recs]

    @app.get("/debug/traces", dependencies=auth)
    def traces() -> list[dict]:
        return ingestor.traces()

    @app.get("/debug/trace/{trace}", dependencies=auth)
    def trace(trace: str) -> list[dict]:
        return ingestor.trace(trace)

    @app.get("/debug/requests", dependencies=auth)
    def requests(status: str | None = None) -> list[dict]:
        return ingestor.requests(status=status)

    @app.get("/debug/liveness", dependencies=auth)
    def liveness() -> list[dict]:
        return ingestor.liveness_grid()

    @app.get("/debug/violations", dependencies=auth)
    def violations() -> list[dict]:
        return ingestor.violations()

    @app.get("/debug/health")        # no auth — ops liveness check of the sidecar itself
    def health() -> dict:
        return ingestor.health()

    @app.get("/debug/rolling", dependencies=auth)
    def rolling(since: float | None = None, until: float | None = None,
                run_id: str | None = None) -> StreamingResponse:
        sink = ingestor.rolling
        if sink is None:
            raise HTTPException(status_code=404, detail="rolling sink not enabled")

        def gen():
            for rec in sink.read(since=since, until=until, run_id=run_id):
                yield json.dumps(rec) + "\n"

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.get("/debug/snapshots", dependencies=auth)
    def snapshots() -> list[dict]:
        return ingestor.snapshot.list() if ingestor.snapshot is not None else []

    @app.get("/debug/snapshot/{sid}", dependencies=auth)
    def snapshot(sid: str) -> PlainTextResponse:
        body = ingestor.snapshot.read(sid) if ingestor.snapshot is not None else None
        if body is None:
            raise HTTPException(status_code=404, detail="no such snapshot")
        return PlainTextResponse(body, media_type="application/x-ndjson")

    @app.post("/debug/capture/start", dependencies=auth)
    def capture_start(body: dict) -> dict:
        return {"capture_id": ingestor.capture_start((body or {}).get("name", "capture"))}

    @app.post("/debug/capture/stop", dependencies=auth)
    def capture_stop(body: dict) -> dict:
        n = ingestor.capture_stop((body or {}).get("capture_id", ""))
        if n < 0:
            raise HTTPException(status_code=404, detail="no such capture")
        return {"event_count": n}

    @app.get("/debug/capture/{cid}/export", dependencies=auth)
    def capture_export(cid: str) -> PlainTextResponse:
        body = ingestor.export_jsonl(cid)
        if body is None:
            raise HTTPException(status_code=404, detail="no such capture")
        return PlainTextResponse(body, media_type="application/x-ndjson",
                                 headers={"Content-Disposition": f'attachment; filename="{cid}.jsonl"'})

    @app.websocket("/debug/stream")
    async def stream(ws: WebSocket, token: str | None = Query(default=None), level: str | None = None,
                     subsystem: str | None = None, topic: str | None = None) -> None:
        if not await checker.check(token):
            await ws.close(code=4401)
            return
        await ws.accept()
        q = ingestor.subscribe()
        order = ("debug", "info", "warning", "error", "critical")
        min_lv = order.index(level) if level in order else None
        try:
            while True:
                r = await q.get()
                if min_lv is not None and (r.level not in order or order.index(r.level) < min_lv):
                    continue
                if subsystem and r.subsystem != subsystem:
                    continue
                if topic and not r.subtopic.startswith(topic):
                    continue
                await ws.send_json(r.to_dict())
        except WebSocketDisconnect:
            pass
        finally:
            ingestor.unsubscribe(q)

    # Live diagnostics level — relayed over HTTP to the CORE, never the cmd/ tree
    # (REMOTE_DEBUG.md §0/§3.5). The caller's Authorization is forwarded, so changing
    # a core diag level needs a real core login token (the static debug token, which
    # is for reading captures while the core is down, is not accepted by the core).
    async def _relay(method: str, path: str, authorization: str | None, body: dict | None) -> dict:
        headers = {"Authorization": authorization} if authorization else {}
        url = f"{config.core_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.request(method, url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"core unreachable: {exc}") from exc
        if r.status_code >= 400:
            detail = "core rejected the request"
            try:
                detail = r.json().get("detail", detail)
            except Exception:  # noqa: BLE001
                pass
            raise HTTPException(status_code=r.status_code,
                                detail=f"/diag/level relay: {detail} (needs a core login token)")
        return r.json()

    @app.get("/debug/level", dependencies=auth)
    async def get_level(authorization: str | None = Header(default=None)) -> dict:
        return await _relay("GET", "/diag/level", authorization, None)

    @app.post("/debug/level", dependencies=auth)
    async def set_level(body: dict, authorization: str | None = Header(default=None)) -> dict:
        return await _relay("PUT", "/diag/level", authorization, body)

    @app.get("/")
    def ui() -> FileResponse:
        return FileResponse(_UI)

    return app

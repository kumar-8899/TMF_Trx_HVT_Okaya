"""Web shell (CORE.md §1, §5).

FastAPI shell: routing, CORS, request-id, RFC-7807 error bodies, and the
mount/health surfaces. Failures are loud and structured — every error leaves as
a ProblemDetail, never a bare string (PRINCIPLES §6, LABVIEW_BRIDGE §11 rule 6).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
ReadyCheck = Callable[[], Awaitable[bool]]


def problem(
    request: Request,
    *,
    status: int,
    title: str,
    detail: str | None = None,
    type_: str = "about:blank",
) -> JSONResponse:
    body = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": str(request.url.path),
        "request_id": getattr(request.state, "request_id", None),
    }
    return JSONResponse(
        body,
        status_code=status,
        media_type=PROBLEM_JSON,
        headers={"X-Request-ID": body["request_id"] or ""},
    )


class WebShell:
    """Handed to modules so they can mount routers under a prefix (CORE.md §4)."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def mount(self, router, prefix: str = "") -> None:
        if router is not None:
            self.app.include_router(router, prefix=prefix.rstrip("/"))

    def add_ready_check(self, name: str, check: ReadyCheck) -> None:
        self.app.state.ready_checks[name] = check


def install_web(app: FastAPI) -> WebShell:
    app.state.ready_checks = {}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local dev; the central edge tightens this
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from core.services.audit import install_audit
    install_audit(app)   # LOGS.md §12: every state-changing request -> action_log / error_log

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        return problem(request, status=exc.status_code, title=str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        return problem(
            request, status=422, title="Request validation failed", detail=str(exc.errors())
        )

    @app.exception_handler(Exception)
    async def unhandled_exc(request: Request, exc: Exception):
        # Was a bare 500 with NOTHING recorded - every unexpected backend crash was invisible.
        try:
            core = getattr(request.app.state, "core", None)
            if core is not None:
                core.diag.exception("http", f"unhandled exception: {request.method} {request.url.path}",
                                    exc, method=request.method, path=request.url.path,
                                    request_id=getattr(request.state, "request_id", None))
        except Exception:  # noqa: BLE001 - logging must not mask the 500
            pass
        return problem(
            request, status=500, title="Internal Server Error", detail=type(exc).__name__
        )

    return WebShell(app)

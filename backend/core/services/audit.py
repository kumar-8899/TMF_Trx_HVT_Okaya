"""Central audit of every state-changing HTTP request (LOGS.md §12).

Why central: LOGS.md §0.2 made actions an explicit `record_action(...)` call, but no module ever made
the call - on a real station the action log held only the controller's run events. Per-endpoint calls
cannot be enforced (a new endpoint just forgets), so the audit hook sits in front of the whole app:

  * EVERY POST/PUT/PATCH/DELETE is recorded in `action_log` (who, what, target, result) unless its route
    is on `READ_ONLY_POSTS` - POSTs that only read (batch reads, validations, connection probes). The
    default is "audited", so a new endpoint is covered without anyone remembering to call anything.
  * Failures reach `error_log`: 5xx -> error, 401/403 -> warning (security), plus the real exception
    (type, message, traceback) for anything that escapes a handler. `web.unhandled_exc` used to return
    a bare 500 and record nothing at all.
  * Secrets never enter a record: request bodies are NOT stored - only their top-level key names, and
    for login only the username.

Never raises into the request path: audit is best-effort, and a logging failure must not fail a request.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import Request

from core.services.auth_verify import AuthError, Principal

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# POST routes that only READ or probe - not actions. Matched against the route TEMPLATE
# (e.g. "/variables/read"). Keep this list short and explicit: anything
# not here is audited, which is the safe default.
_READ_ONLY_DEFAULT = (
    r"^/variables/read$",
    r"^/recipes/validate$",
    r"^/recipes/\{[^}]+\}/versions/\{[^}]+\}/validate$",
    r"^/mes/db/(test|databases|tables|columns|values|verify|inbound/check|outbound/validate)$",
    r"^/reports/db-config/test$",
    r"^/config/instruments/test$",
    r"^/license/request$",
    r"^/update/check$",
)
READ_ONLY_POSTS: list[re.Pattern] = [re.compile(p) for p in _READ_ONLY_DEFAULT]


def register_read_only_post(pattern: str) -> None:
    """Apps/forks: mark one of THEIR read-only POST routes (regex on the route template) as not an action."""
    READ_ONLY_POSTS.append(re.compile(pattern))


# Friendly action names for the endpoints operators and auditors care about; any other mutating
# route falls back to "<method> <template>" so nothing is ever unnamed.
_ACTION_NAMES: dict[tuple[str, str], str] = {
    ("POST", "/auth/login"): "auth.login",
    ("POST", "/auth/logout"): "auth.logout",
    ("POST", "/auth/change-password"): "auth.change_password",
    ("PUT", "/auth/roles/{role}"): "auth.role_permissions",
    ("POST", "/auth/users"): "auth.user_create",
    ("PUT", "/auth/users/{name}/role"): "auth.user_role",
    ("POST", "/auth/users/{name}/lock"): "auth.user_lock",
    ("POST", "/auth/users/{name}/unlock"): "auth.user_unlock",
    ("POST", "/auth/users/{name}/activate"): "auth.user_activate",
    ("POST", "/auth/users/{name}/deactivate"): "auth.user_deactivate",
    ("POST", "/auth/users/{name}/reset-password"): "auth.user_reset_password",
    ("POST", "/runs/start"): "run.request_start",
    ("POST", "/runs/abort"): "run.request_abort",
    ("POST", "/runs/reset-data"): "system.reset_data",
    ("POST", "/recipes"): "recipe.create",
    ("POST", "/recipes/import"): "recipe.import",
    ("PUT", "/recipes/{recipe_id}/drafts/{draft_id}"): "recipe.draft_save",
    ("POST", "/recipes/{recipe_id}/drafts/{draft_id}/publish"): "recipe.publish",
    ("POST", "/recipes/{recipe_id}/deprecate"): "recipe.deprecate",
    ("POST", "/recipes/{recipe_id}/versions/{n}/archive"): "recipe.archive",
    ("POST", "/config/instruments"): "config.instrument_add",
    ("PUT", "/config/instruments/{iid}"): "config.instrument_edit",
    ("DELETE", "/config/instruments/{iid}"): "config.instrument_delete",
    ("PUT", "/config/shift"): "config.shift",
    ("PUT", "/config/barcode"): "config.barcode",
    ("PUT", "/branding"): "config.branding",
    ("PUT", "/system/station-config"): "system.station_config",
    ("PUT", "/system/debug-config"): "system.debug_config",
    ("PUT", "/diag/level"): "system.log_level",
    ("POST", "/system/relaunch"): "system.relaunch",
    ("POST", "/system/shutdown"): "system.shutdown",
    ("POST", "/license/activate"): "system.license_activate",
    ("POST", "/update/install-file"): "system.update_install",
    ("POST", "/update/download"): "system.update_download",
    ("POST", "/update/ingest"): "system.update_ingest",
    ("POST", "/update/scan-incoming"): "system.update_scan",
    ("POST", "/update/relaunch/{release_id}"): "system.update_relaunch",
    ("POST", "/update/apply/{release_id}"): "system.update_apply",
    ("POST", "/update/rollback"): "system.update_rollback",
    ("POST", "/health/maintenance/enter"): "maintenance.enter",
    ("POST", "/health/maintenance/exit"): "maintenance.exit",
    ("POST", "/variables/write"): "variables.write",
    ("PUT", "/variables/{name}/value"): "variables.write",
    ("POST", "/variables/instances/{instance_id}/call"): "instrument.call",
    ("POST", "/health/run"): "health.run",
    ("PUT", "/health/schedule"): "health.schedule",
    ("PUT", "/mes/config"): "mes.config",
    ("PUT", "/mes/db-config"): "mes.db_config",
    ("PUT", "/reports/db-config"): "report.db_config",
    ("POST", "/variables/bindings"): "variables.binding_add",
    ("PUT", "/variables/bindings/{name}"): "variables.binding_edit",
    ("DELETE", "/variables/bindings/{name}"): "variables.binding_delete",
    ("DELETE", "/logs/errors"): "logs.purge_errors",
    ("DELETE", "/logs/actions"): "logs.purge_actions",
}

_SYSTEM_STATUS_ERROR = 500
_MAX_ERR = 300


def register_action_name(method: str, template: str, name: str) -> None:
    """Apps/forks: give one of THEIR mutating routes a friendly action name."""
    _ACTION_NAMES[(method.upper(), template)] = name


def is_read_only_post(template: str) -> bool:
    return any(p.match(template) for p in READ_ONLY_POSTS)


def action_name(method: str, template: str) -> str:
    return _ACTION_NAMES.get((method, template)) or f"{method.lower()} {template}"


def _principal(request: Request) -> Principal | None:
    auth = getattr(request.app.state, "auth", None)
    header = request.headers.get("Authorization", "")
    if auth is None or not header.startswith("Bearer "):
        return None
    try:
        return auth.verify(header[7:].strip())
    except (AuthError, Exception):  # noqa: BLE001 - an unverifiable token is "unknown", not a crash
        return None


def _logs_contract(request: Request) -> Any:
    core = getattr(request.app.state, "core", None)
    contracts = getattr(core, "contracts", None) or {}
    return contracts.get("logs") if hasattr(contracts, "get") else None


def _diag(request: Request) -> Any:
    core = getattr(request.app.state, "core", None)
    return getattr(core, "diag", None)


async def _body_keys(request: Request, template: str) -> tuple[list[str], str | None]:
    """Top-level key names of a JSON body - never values. For login, also the username (and only that)."""
    try:
        raw = await request.body()
        data = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return [], None
    if not isinstance(data, dict):
        return [], None
    user = None
    if template in ("/auth/login",):
        u = data.get("username")
        user = u if isinstance(u, str) else None
    return sorted(str(k) for k in data)[:30], user


def _target(request: Request) -> str:
    params = request.scope.get("path_params") or {}
    return "/".join(str(v) for v in params.values()) or request.url.path


async def _error_text(response) -> str | None:
    """Short title/detail of an RFC-7807 error body, without disturbing the response."""
    try:
        chunks = [c async for c in response.body_iterator]
    except Exception:  # noqa: BLE001
        return None
    body = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)

    async def _replay():
        yield body

    response.body_iterator = _replay()
    try:
        d = json.loads(body)
        return " - ".join(str(x) for x in (d.get("title"), d.get("detail")) if x)[:_MAX_ERR] or None
    except Exception:  # noqa: BLE001
        return body[:_MAX_ERR].decode("utf-8", "replace") or None


def install_audit(app) -> None:
    """Register the audit middleware. Called from `web.install_web`."""

    @app.middleware("http")
    async def audit_mw(request: Request, call_next):
        method = request.method
        if method not in MUTATING:
            return await call_next(request)

        t0 = time.perf_counter()
        try:
            keys, login_user = await _body_keys(request, request.url.path)
        except Exception:  # noqa: BLE001
            keys, login_user = [], None
        err = None
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - audited here, then re-raised to the 500 handler
            err = exc
            response = None
        status = 500 if response is None else response.status_code
        # the route template is only known after routing
        route = request.scope.get("route")
        template = getattr(route, "path", None) or request.url.path
        if response is not None and status >= 400:
            reason = await _error_text(response)
        else:
            reason = f"{type(err).__name__}: {err}"[:_MAX_ERR] if err else None

        try:
            await _record(request, method, template, status, t0, keys, login_user, reason, err)
        except Exception:  # noqa: BLE001 - audit must never fail the request
            pass
        if err is not None:
            raise err
        return response


async def _record(request, method, template, status, t0, keys, login_user, reason, exc) -> None:
    diag = _diag(request)
    rid = getattr(request.state, "request_id", None)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    ok = status < 400

    # --- error_log: what went wrong -----------------------------------------------------------
    if diag is not None:
        ctx = {"method": method, "route": template, "status": status, "request_id": rid, "ms": ms}
        if reason:
            ctx["reason"] = reason
        if exc is not None:
            pass  # the traceback is recorded once, by web.unhandled_exc (it also sees GETs)
        elif status >= _SYSTEM_STATUS_ERROR:
            diag.error("http", f"{method} {template} -> {status}", **ctx)
        elif status in (401, 403):
            diag.warning("security", f"access denied: {method} {template} -> {status}", **ctx)

    # --- action_log: what was done -------------------------------------------------------------
    if method == "POST" and is_read_only_post(template):
        return
    logs = _logs_contract(request)
    if logs is None:
        return
    principal = _principal(request)
    if principal is None:
        who = login_user or "anonymous"
        principal = Principal(subject=who, role="anonymous", permissions=frozenset())
    detail = {"status": status, "route": f"{method} {template}", "path": request.url.path,
              "request_id": rid, "ms": ms, "fields": keys}
    if reason:
        detail["reason"] = reason
    client = getattr(request.client, "host", None)
    if client:
        detail["client"] = client
    await logs.record_action(principal, action_name(method, template), _target(request),
                             "success" if ok else "failure", detail)

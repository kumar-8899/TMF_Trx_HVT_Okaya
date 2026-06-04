"""Auth dependencies shared by all modules (CORE.md §6.4).

FastAPI dependencies that gate routes on the permission set carried by the
Principal. Modules import these from core; they never touch the Auth package.
Errors raise HTTPException → RFC-7807 via the handlers in web.py.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request

from core.services.auth_verify import AuthError, Principal


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip() or None
    return None


def current_principal(request: Request) -> Principal:
    """Resolve the bearer token to a Principal (401 if missing/invalid)."""
    auth = getattr(request.app.state, "auth", None)
    token = _bearer(request)
    if auth is None or token is None:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
    try:
        return auth.verify(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_permission(*perms: str) -> Callable[[Request], Awaitable[Principal]]:
    """Primary gate: 401 (no/invalid token) / 403 (lacks any listed permission)."""

    async def dep(request: Request) -> Principal:
        principal = current_principal(request)
        missing = [p for p in perms if not principal.has_permission(p)]
        if missing:
            raise HTTPException(status_code=403, detail=f"requires permission(s): {', '.join(missing)}")
        return principal

    return dep


def require_role(*roles: str) -> Callable[[Request], Awaitable[Principal]]:
    """Secondary convenience gate by role name."""

    async def dep(request: Request) -> Principal:
        principal = current_principal(request)
        if roles and principal.role not in roles:
            raise HTTPException(status_code=403, detail=f"requires role: {', '.join(roles)}")
        return principal

    return dep

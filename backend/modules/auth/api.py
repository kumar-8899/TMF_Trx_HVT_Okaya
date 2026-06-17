"""Auth router (prefix handled as absolute paths; mounts at empty prefix)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from core.services.auth_verify import AuthError, Principal
from core.services.security import require_permission
from modules.auth.policy import PolicyError
from modules.auth.users import DuplicateUser, ProtectedUserError, UserNotFound


async def _mgmt(coro):
    try:
        return await coro
    except DuplicateUser as exc:
        raise HTTPException(status_code=409, detail=f"user exists: {exc}") from exc
    except ProtectedUserError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except UserNotFound as exc:
        raise HTTPException(status_code=404, detail=f"no user: {exc}") from exc
    except PolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        token = header[7:].strip()
        if token:
            return token
    raise HTTPException(status_code=401, detail="missing bearer token")


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["auth"])

    @router.post("/auth/login")
    async def login(body: dict) -> dict:
        username = body.get("username")
        credential = body.get("credential") or {}
        if not username:
            raise HTTPException(status_code=422, detail="username required")
        try:
            return await module.login(username, credential)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @router.post("/auth/logout")
    async def logout(request: Request) -> dict:
        try:
            return await module.logout(_token(request))
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @router.get("/auth/me")
    async def me(request: Request) -> dict:
        try:
            return await module.whoami(_token(request))
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    @router.post("/auth/change-password")
    async def change_password(body: dict, request: Request) -> dict:
        try:
            return await module.change_password(_token(request), body.get("old", ""), body.get("new", ""))
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- user management — all gated on AUTH.MANAGE_USERS -------------------
    # The dependency returns the requesting Principal, so handlers can scope by
    # the viewer's role (super_admin visibility + role-assignment rules).
    manage = Depends(require_permission("AUTH.MANAGE_USERS"))

    @router.get("/auth/users")
    async def list_users(principal: Principal = manage) -> list[dict]:
        return await module.list_users(principal.role)

    @router.get("/auth/roles")
    async def list_roles(principal: Principal = manage) -> list[str]:
        return module.list_assignable_roles(principal.role)

    @router.post("/auth/users", status_code=201)
    async def create_user(body: dict, principal: Principal = manage) -> dict:
        if not body.get("username") or not body.get("role"):
            raise HTTPException(status_code=422, detail="username and role required")
        return await _mgmt(module.create_user(body["username"], body["role"], principal.role))

    @router.get("/auth/users/{name}")
    async def get_user(name: str, principal: Principal = manage) -> dict:
        return await _mgmt(module.get_user(name, principal.role))

    @router.put("/auth/users/{name}/role")
    async def set_role(name: str, body: dict, principal: Principal = manage) -> dict:
        if not body.get("role"):
            raise HTTPException(status_code=422, detail="role required")
        return await _mgmt(module.set_user_role(name, body["role"], principal.role))

    @router.post("/auth/users/{name}/lock")
    async def lock(name: str, principal: Principal = manage) -> dict:
        return await _mgmt(module.lock(name))

    @router.post("/auth/users/{name}/unlock")
    async def unlock(name: str, principal: Principal = manage) -> dict:
        return await _mgmt(module.unlock(name))

    @router.post("/auth/users/{name}/activate")
    async def activate(name: str, principal: Principal = manage) -> dict:
        return await _mgmt(module.activate(name))

    @router.post("/auth/users/{name}/deactivate")
    async def deactivate(name: str, principal: Principal = manage) -> dict:
        return await _mgmt(module.deactivate(name))

    @router.post("/auth/users/{name}/reset-password")
    async def reset_password(name: str, body: dict | None = None, principal: Principal = manage) -> dict:
        temp = (body or {}).get("temp_password")
        return await _mgmt(module.admin_reset_password(name, temp))

    return router


"""Auth router (prefix handled as absolute paths; mounts at empty prefix)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from core.services.auth_verify import AuthError
from modules.auth.policy import PolicyError


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

    return router

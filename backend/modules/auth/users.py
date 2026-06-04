"""User + credential stores over the base Repository (CORE.md §7).

Record types `user` and `credential` — excluded from future RAG ingestion
(operational + secrets). No secret ever lands on the user record.
"""

from __future__ import annotations

import time

# User states (MD).
ACTIVE = "ACTIVE"
LOCKED = "LOCKED"
INACTIVE = "INACTIVE"
PASSWORD_RESET_REQUIRED = "PASSWORD_RESET_REQUIRED"

LOGIN_BLOCKED = {LOCKED, INACTIVE}


class UserStore:
    def __init__(self, db) -> None:
        self._db = db

    async def get(self, username: str) -> dict | None:
        rec = await self._db.repo.get("user", username)
        return rec["data"] if rec else None

    async def exists(self, username: str) -> bool:
        return await self.get(username) is not None

    async def list(self) -> list[dict]:
        return [r["data"] for r in await self._db.repo.query("user")]

    async def create(self, username: str, role: str, state: str = ACTIVE) -> dict:
        now = time.time()
        data = {
            "username": username,
            "role": role,
            "state": state,
            "created_ts": now,
            "last_login_ts": None,
            "pw_updated_ts": now,
        }
        await self._db.repo.put("user", data, id=username, summary=f"user {username}")
        return data

    async def _update(self, username: str, **changes) -> dict:
        data = await self.get(username)
        if data is None:
            raise KeyError(username)
        data.update(changes)
        await self._db.repo.put("user", data, id=username, summary=f"user {username}")
        return data

    async def set_state(self, username: str, state: str) -> dict:
        return await self._update(username, state=state)

    async def set_role(self, username: str, role: str) -> dict:
        return await self._update(username, role=role)

    async def touch_login(self, username: str) -> None:
        await self._update(username, last_login_ts=time.time())

    async def mark_password_updated(self, username: str) -> None:
        await self._update(username, pw_updated_ts=time.time())


class CredentialStore:
    """Per-user, per-method secret (split from identity so biometric slots in)."""

    def __init__(self, db) -> None:
        self._db = db

    async def get(self, username: str, method: str) -> dict | None:
        rec = await self._db.repo.get("credential", f"{username}:{method}")
        return rec["data"]["secret"] if rec else None

    async def set(self, username: str, method: str, secret: dict) -> None:
        await self._db.repo.put(
            "credential",
            {"username": username, "method": method, "secret": secret},
            id=f"{username}:{method}",
            summary=f"credential {username}:{method}",
        )

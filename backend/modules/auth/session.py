"""Session manager — issue / verify / revoke, single active session.

verify() is **synchronous** (the core.auth port is sync): sessions are held in
memory and that is authoritative for verification. The DB is persistence/audit +
restore-on-boot. Sessions are per-station, never bridged (BRIDGE §2).
"""

from __future__ import annotations

import secrets
import time

from core.services.auth_verify import AuthError, Principal


class SessionManager:
    def __init__(self, db, ttl_min: int = 480) -> None:
        self._db = db
        self._ttl = ttl_min * 60
        self._sessions: dict[str, dict] = {}  # token -> data (authoritative for verify)

    async def load_active(self) -> None:
        """Restore non-revoked, non-expired sessions on boot."""
        now = time.time()
        for rec in await self._db.repo.query("session"):
            d = rec["data"]
            if not d.get("revoked") and d.get("expires", 0) > now:
                self._sessions[rec["id"]] = d

    async def issue(self, username: str, role: str, permissions: list[str]) -> dict:
        await self._revoke_user_sessions(username)  # single active session
        token = secrets.token_urlsafe(32)
        now = time.time()
        data = {
            "username": username,
            "role": role,
            "permissions": permissions,
            "created": now,
            "expires": now + self._ttl,
            "revoked": False,
        }
        self._sessions[token] = data
        await self._db.repo.put("session", data, id=token, summary=f"session {username}")
        return {"token": token, "expires": data["expires"]}

    def verify(self, token: str) -> Principal:
        data = self._sessions.get(token)
        if data is None or data["revoked"] or data["expires"] < time.time():
            raise AuthError("invalid or expired session")
        return Principal(
            subject=data["username"],
            role=data["role"],
            permissions=frozenset(data["permissions"]),
        )

    async def revoke(self, token: str) -> None:
        data = self._sessions.pop(token, None)
        if data is not None:
            data["revoked"] = True
            await self._db.repo.put("session", data, id=token, summary=f"session {data['username']}")

    async def _revoke_user_sessions(self, username: str) -> None:
        for token, data in list(self._sessions.items()):
            if data["username"] == username:
                await self.revoke(token)

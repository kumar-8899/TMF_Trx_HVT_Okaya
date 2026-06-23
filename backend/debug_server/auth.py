"""Token check (DEBUG_SERVER.md §8) — validate bearer against the core's /auth/me.

The sidecar has no core.auth injection (§2); it validates the same tokens over
HTTP. Small positive cache so a live WS tail does not hammer /auth/me.
"""

from __future__ import annotations

import time

import httpx


class TokenChecker:
    def __init__(self, core_url: str, *, require_auth: bool = True, ttl: float = 30.0) -> None:
        self.core_url = core_url.rstrip("/")
        self.require_auth = require_auth
        self._ttl = ttl
        self._cache: dict[str, float] = {}   # token -> expiry

    async def check(self, token: str | None) -> bool:
        if not self.require_auth:
            return True
        if not token:
            return False
        now = time.time()
        exp = self._cache.get(token)
        if exp and exp > now:
            return True
        try:
            async with httpx.AsyncClient(timeout=4.0) as c:
                r = await c.get(f"{self.core_url}/auth/me", headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError:
            return False
        if r.status_code == 200:
            self._cache[token] = now + self._ttl
            return True
        return False

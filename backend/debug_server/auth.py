"""Token check (DEBUG_SERVER.md §8, REMOTE_DEBUG.md §3.2).

Two credentials, checked in order:
  1. A static `debug.token`, validated by the sidecar **itself, in-process, with no
     call to the core** — this is the path that works when the core is down, which is
     exactly when the sidecar is needed most (REMOTE_DEBUG §0/§13.2).
  2. The core bearer, validated over HTTP against `/auth/me` (a convenience for
     developers already holding a core token), with a small positive cache so a live
     WS tail does not hammer the endpoint.
"""

from __future__ import annotations

import hmac
import time

import httpx


class TokenChecker:
    def __init__(self, core_url: str, *, require_auth: bool = True, ttl: float = 30.0,
                 static_token: str | None = None) -> None:
        self.core_url = core_url.rstrip("/")
        self.require_auth = require_auth
        self.static_token = static_token or None
        self._ttl = ttl
        self._cache: dict[str, float] = {}   # token -> expiry

    async def check(self, token: str | None) -> bool:
        if not self.require_auth:
            return True
        if not token:
            return False
        # 1. Static token — constant-time compare, zero core dependency (§13.2).
        if self.static_token is not None and hmac.compare_digest(token, self.static_token):
            return True
        # 2. Core bearer fallback.
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

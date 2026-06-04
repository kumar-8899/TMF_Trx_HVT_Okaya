"""Dev-only authenticator: accepts any credential. Never ship enabled."""

from __future__ import annotations


class NoAuthAuthenticator:
    method_id = "no_auth"

    async def authenticate(self, username: str, submitted: dict, stored: dict | None) -> bool:
        return True

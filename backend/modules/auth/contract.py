"""Auth contract (CORE.md §2, §6.4) — permission-first.

The module is fixed; the only pluggable seam is the `Authenticator` (the
credential check), so biometric later is one class + a config value, with no
change to sessions, users, audit, or the core port (the biometric-readiness
rule). See docs/contracts/auth.md for the permission grammar and locked rules.
"""

from __future__ import annotations

from typing import Protocol

from core.services.auth_verify import Principal  # re-export

__all__ = ["AuthContract", "Authenticator", "Principal"]


class Authenticator(Protocol):
    """The single pluggable seam: verify a credential for a user.

    The module owns everything after a True/False result (session issue, state
    checks, single-session revoke, audit). A new method = one class + config.
    """

    method_id: str  # "password" | "no_auth" | "biometric"

    async def authenticate(
        self, username: str, submitted: dict, stored: dict | None
    ) -> bool:
        """`submitted` = the credential from the request ({"password": ...} /
        {"template": ...}); `stored` = the user's stored secret for this method
        ({"argon2_hash": ...}) or None. The module owns everything after."""
        ...


class AuthContract(Protocol):
    async def login(self, username: str, credential: dict) -> dict:
        """-> {token, expires, principal}. credential is a dict so biometric
        ({"template": ...}) fits without a contract change; password is
        {"password": ...}."""
        ...

    async def logout(self, token: str) -> dict: ...
    async def change_password(self, token: str, old: str, new: str) -> dict: ...
    async def whoami(self, token: str) -> Principal: ...

"""Token-verification port (CORE.md §6.4).

Verification depends on the auth scheme (DB sessions / JWT / SSO), so the core
exposes `core.auth` as a PORT. The active Auth variant registers its verifier
here at init. Every other module uses this and never touches the Auth package.

If no Auth module is loaded, the port rejects all tokens (fail-closed). A
dev-only `no-auth` verifier exists for local work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


class AuthError(Exception):
    """Token rejected."""


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: tuple[str, ...] = ()
    claims: dict = field(default_factory=dict)


VerifierFn = Callable[[str], Principal]


def _fail_closed(_token: str) -> Principal:
    raise AuthError("no auth verifier registered (fail-closed)")


def no_auth_verifier(_token: str) -> Principal:
    """Dev-only: accept anything as a local admin. Never ship enabled."""
    return Principal(subject="dev", roles=("admin",))


class TokenVerifier:
    def __init__(self) -> None:
        self._verify: VerifierFn = _fail_closed

    def register(self, verifier: VerifierFn) -> None:
        self._verify = verifier

    def verify(self, token: str) -> Principal:
        return self._verify(token)

    def require_role(self, token: str, *roles: str) -> Principal:
        principal = self.verify(token)
        if roles and not set(roles) & set(principal.roles):
            raise AuthError(f"requires one of roles: {', '.join(roles)}")
        return principal

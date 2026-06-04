"""Token-verification port (CORE.md §6.4) — permission-first.

Authorization consumes **permissions** (`DOMAIN.ACTION`), never roles. The active
Auth variant registers its verifier here at init; the permission set is resolved
at login and rides on the `Principal`. Every other module uses `core.auth` and
never touches the Auth package.

If no Auth module is loaded, the port rejects all tokens (fail-closed). A
dev-only `no_auth` verifier exists for local work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


class AuthError(Exception):
    """Token rejected, or principal lacks a required permission/role."""


def permission_granted(held: frozenset[str], needed: str) -> bool:
    """Wildcard-aware match: `*` grants all, `DOMAIN.*` grants any action in DOMAIN."""
    if "*" in held or needed in held:
        return True
    domain = needed.split(".", 1)[0]
    return f"{domain}.*" in held


@dataclass(frozen=True)
class Principal:
    subject: str                                  # username
    role: str = ""
    permissions: frozenset[str] = frozenset()
    claims: dict = field(default_factory=dict)

    def has_permission(self, perm: str) -> bool:
        return permission_granted(self.permissions, perm)


VerifierFn = Callable[[str], Principal]


def _fail_closed(_token: str) -> Principal:
    raise AuthError("no auth verifier registered (fail-closed)")


def no_auth_verifier(_token: str) -> Principal:
    """Dev-only: accept anything as a local admin with all permissions."""
    return Principal(subject="dev", role="admin", permissions=frozenset({"*"}))


class TokenVerifier:
    def __init__(self) -> None:
        self._verify: VerifierFn = _fail_closed

    def register(self, verifier: VerifierFn) -> None:
        self._verify = verifier

    def verify(self, token: str) -> Principal:
        return self._verify(token)

    def require_permission(self, token: str, *perms: str) -> Principal:
        principal = self.verify(token)
        missing = [p for p in perms if not principal.has_permission(p)]
        if missing:
            raise AuthError(f"requires permission(s): {', '.join(missing)}")
        return principal

    def require_role(self, token: str, *roles: str) -> Principal:
        principal = self.verify(token)
        if roles and principal.role not in roles:
            raise AuthError(f"requires one of roles: {', '.join(roles)}")
        return principal

"""Auth `local_db` variant — the fixed module; authenticator chosen by config.

Fills the core.auth port with a synchronous session verifier, persists users /
credentials / sessions via the Repository, resolves permissions from the role map
at login, enforces single active session + the user state machine, and emits
audit diagnostics.
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.auth_verify import AuthError
from modules.auth.api import build_router
from modules.auth.authenticators import make_authenticator
from modules.auth.authenticators.password import hash_password, verify_password
from modules.auth.policy import PasswordPolicy
from modules.auth.session import SessionManager
from modules.auth.users import (
    ACTIVE,
    LOGIN_BLOCKED,
    PASSWORD_RESET_REQUIRED,
    CredentialStore,
    UserStore,
)


class LocalDbAuth:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.roles: dict[str, list[str]] = config.get("roles", {})
        self.method_id = config.get("authenticator", "password")
        self.authenticator = make_authenticator(self.method_id)
        self.policy = PasswordPolicy(config.get("password_policy"))
        self.users = UserStore(core.db)
        self.creds = CredentialStore(core.db)
        self.sessions = SessionManager(core.db, ttl_min=config.get("session_ttl_min", 480))
        self.router = build_router(self)
        self.mqtt_handlers: list = []

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "LocalDbAuth":
        return cls(core, config)

    async def init(self) -> None:
        # Fill the core.auth port with the (sync) session verifier (CORE.md §6.4).
        self.core.auth.register(self.sessions.verify)
        await self.sessions.load_active()
        await self._seed_users()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK, detail=f"authenticator={self.method_id}")

    # --- seeding -----------------------------------------------------------

    async def _seed_users(self) -> None:
        for entry in self.config.get("users", []):
            username = entry["username"]
            if await self.users.exists(username):
                continue
            await self.users.create(username, entry["role"], state=ACTIVE)
            if entry.get("password"):
                await self.creds.set(username, "password", {"argon2_hash": hash_password(entry["password"])})
            self.core.diag.info("auth", "user seeded", user=username, role=entry["role"])

    # --- permission resolution (at login) ----------------------------------

    def _resolve_permissions(self, role: str) -> list[str]:
        return sorted(set(self.roles.get(role, [])))

    # --- contract ----------------------------------------------------------

    async def login(self, username: str, credential: dict) -> dict:
        user = await self.users.get(username)
        if user is None:
            raise AuthError("invalid credentials")
        if user["state"] in LOGIN_BLOCKED:
            raise AuthError(f"user {user['state'].lower()}")
        stored = await self.creds.get(username, self.authenticator.method_id)
        if not await self.authenticator.authenticate(username, credential, stored):
            raise AuthError("invalid credentials")

        perms = self._resolve_permissions(user["role"])
        issued = await self.sessions.issue(username, user["role"], perms)
        await self.users.touch_login(username)
        self.core.diag.info("auth", "session started", user=username, role=user["role"])
        return {
            "token": issued["token"],
            "expires": issued["expires"],
            "principal": {
                "username": username,
                "role": user["role"],
                "permissions": perms,
                "session_expires": issued["expires"],
                "must_change_password": user["state"] == PASSWORD_RESET_REQUIRED,
            },
        }

    async def logout(self, token: str) -> dict:
        principal = self.sessions.verify(token)  # raises if invalid
        await self.sessions.revoke(token)
        self.core.diag.info("auth", "session ended", user=principal.subject)
        return {"ok": True}

    async def change_password(self, token: str, old: str, new: str) -> dict:
        principal = self.sessions.verify(token)
        username = principal.subject
        stored = await self.creds.get(username, "password")
        if not verify_password(stored, old):
            raise AuthError("old password incorrect")
        self.policy.validate(new)  # PolicyError -> 422
        await self.creds.set(username, "password", {"argon2_hash": hash_password(new)})
        await self.users.set_state(username, ACTIVE)  # clears PASSWORD_RESET_REQUIRED
        await self.users.mark_password_updated(username)
        self.core.diag.info("auth", "password changed", user=username)
        return {"ok": True}

    async def whoami(self, token: str) -> dict:
        p = self.sessions.verify(token)
        return {"username": p.subject, "role": p.role, "permissions": sorted(p.permissions)}

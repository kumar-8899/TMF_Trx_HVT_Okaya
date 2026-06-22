"""Auth `local_db` variant — the fixed module; authenticator chosen by config.

Fills the core.auth port with a synchronous session verifier, persists users /
credentials / sessions via the Repository, resolves permissions from the role map
at login, enforces single active session + the user state machine, and emits
audit diagnostics.
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.auth_verify import AuthError, permission_granted
from modules.auth.api import build_router
from modules.auth.authenticators import make_authenticator
from modules.auth.authenticators.password import hash_password, verify_password
from modules.auth.policy import PasswordPolicy, generate_temp_password
from modules.auth.session import SessionManager
from modules.auth.users import (
    ACTIVE,
    INACTIVE,
    LOCKED,
    LOGIN_BLOCKED,
    PASSWORD_RESET_REQUIRED,
    PROTECTED_ROLE,
    CredentialStore,
    DuplicateUser,
    ProtectedUserError,
    UserNotFound,
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

        # Self-heal: the super_admin singleton must never be left disabled — force
        # it back to ACTIVE on boot (recovers an accidental deactivate/lock).
        for u in await self.users.list():
            if u.get("role") == PROTECTED_ROLE and u.get("state") in LOGIN_BLOCKED:
                await self.users.set_state(u["username"], ACTIVE)
                self.core.diag.warning("auth", "super_admin re-activated on boot", user=u["username"])

    # --- permission resolution (at login) ----------------------------------

    def _resolve_permissions(self, role: str) -> list[str]:
        return sorted(set(self.roles.get(role, [])))

    # --- role assignment policy --------------------------------------------

    def _is_elevated(self, role: str) -> bool:
        """A role that can itself manage users (e.g. admin). Only super_admin may
        grant these — keeps an admin from minting more admins."""
        return permission_granted(frozenset(self.roles.get(role, [])), "AUTH.MANAGE_USERS")

    def list_assignable_roles(self, viewer_role: str) -> list[str]:
        """Roles the viewer may assign when creating/editing a user.
        - super_admin is never assignable (protected singleton).
        - user-management roles are assignable only by super_admin."""
        viewer_is_super = viewer_role == PROTECTED_ROLE
        out = [
            role for role in self.roles
            if role != PROTECTED_ROLE and (viewer_is_super or not self._is_elevated(role))
        ]
        return sorted(out)

    def _check_assignable(self, role: str, viewer_role: str) -> None:
        if role not in self.list_assignable_roles(viewer_role):
            raise ProtectedUserError(f"role '{role}' is not assignable by your account")

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

    # --- user management (gated AUTH.MANAGE_USERS in the router) ------------

    async def list_users(self, viewer_role: str = PROTECTED_ROLE) -> list[dict]:
        # super_admin accounts are visible only to a super_admin viewer.
        users = await self.users.list()  # user records carry no secret
        if viewer_role != PROTECTED_ROLE:
            users = [u for u in users if u.get("role") != PROTECTED_ROLE]
        return users

    async def _require_user(self, username: str) -> dict:
        user = await self.users.get(username)
        if user is None:
            raise UserNotFound(username)
        return user

    async def get_user(self, username: str, viewer_role: str = PROTECTED_ROLE) -> dict:
        user = await self._require_user(username)
        # Hide the super_admin account from non-super_admin viewers (as if absent).
        if user["role"] == PROTECTED_ROLE and viewer_role != PROTECTED_ROLE:
            raise UserNotFound(username)
        return user

    async def create_user(self, username: str, role: str, viewer_role: str = PROTECTED_ROLE) -> dict:
        """Create a user with a generated temporary password; the account starts in
        PASSWORD_RESET_REQUIRED so the user must change it on first login."""
        if await self.users.exists(username):
            raise DuplicateUser(username)
        self._check_assignable(role, viewer_role)  # ProtectedUserError -> 403
        temp = generate_temp_password()
        user = await self.users.create(username, role, state=PASSWORD_RESET_REQUIRED)
        await self.creds.set(username, "password", {"argon2_hash": hash_password(temp)})
        self.core.diag.info("auth", "user created", user=username, role=role)
        return {**user, "temp_password": temp}

    async def set_user_role(self, username: str, role: str, viewer_role: str = PROTECTED_ROLE) -> dict:
        user = await self._require_user(username)
        if user["role"] == PROTECTED_ROLE:
            raise ProtectedUserError(f"cannot change the {PROTECTED_ROLE}'s role")
        self._check_assignable(role, viewer_role)  # rejects super_admin + un-grantable roles
        user = await self.users.set_role(username, role)
        self.core.diag.info("auth", "user role changed", user=username, role=role)
        return user

    async def _set_state(self, username: str, state: str, event: str, revoke: bool) -> dict:
        user = await self._require_user(username)
        if user["role"] == PROTECTED_ROLE:
            raise ProtectedUserError(f"{event} not allowed on the {PROTECTED_ROLE}")
        user = await self.users.set_state(username, state)
        if revoke:
            await self.sessions.revoke_user(username)
        self.core.diag.info("auth", event, user=username)
        return user

    async def lock(self, username: str) -> dict:
        return await self._set_state(username, LOCKED, "user locked", revoke=True)

    async def unlock(self, username: str) -> dict:
        return await self._set_state(username, ACTIVE, "user unlocked", revoke=False)

    async def activate(self, username: str) -> dict:
        return await self._set_state(username, ACTIVE, "user activated", revoke=False)

    async def deactivate(self, username: str) -> dict:
        return await self._set_state(username, INACTIVE, "user deactivated", revoke=True)

    async def reset_users(self) -> int:
        """Delete every non-super_admin user (+ credential + sessions). The protected
        super_admin is always kept. For the Settings reset (SYSTEM.RESET_DATA)."""
        n = 0
        for u in await self.users.list():
            if u.get("role") == PROTECTED_ROLE:
                continue
            un = u["username"]
            await self.sessions.revoke_user(un)
            await self.core.db.repo.delete_id("user", un)
            await self.core.db.repo.delete_id("credential", f"{un}:password")
            n += 1
        self.core.diag.warning("auth", "users reset", removed=n)
        return n

    async def admin_reset_password(self, username: str, temp_password: str | None = None) -> dict:
        await self._require_user(username)
        temp = temp_password or generate_temp_password()
        await self.creds.set(username, "password", {"argon2_hash": hash_password(temp)})
        await self.users.set_state(username, PASSWORD_RESET_REQUIRED)
        await self.users.mark_password_updated(username)
        await self.sessions.revoke_user(username)
        self.core.diag.warning("auth", "admin reset password", user=username)
        return {"temp_password": temp}

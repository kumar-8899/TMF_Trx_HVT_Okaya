"""Password authenticator (Argon2). The production credential check."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored: dict | None, password: str) -> bool:
    if not stored or "argon2_hash" not in stored:
        return False
    try:
        return _ph.verify(stored["argon2_hash"], password)
    except (VerifyMismatchError, Exception):  # noqa: BLE001 — any verify failure = reject
        return False


class PasswordAuthenticator:
    method_id = "password"

    async def authenticate(self, username: str, submitted: dict, stored: dict | None) -> bool:
        return verify_password(stored, submitted.get("password", ""))

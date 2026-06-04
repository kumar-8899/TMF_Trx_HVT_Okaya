"""Password policy + temp-password generation (MD: Password Policy Manager)."""

from __future__ import annotations

import secrets
import string


class PolicyError(Exception):
    """Password fails the configured policy. Maps to HTTP 422."""


class PasswordPolicy:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.min_length = int(cfg.get("min_length", 8))
        self.require_mixed_case = bool(cfg.get("require_mixed_case", False))
        self.require_digit = bool(cfg.get("require_digit", False))
        self.max_age_days = int(cfg.get("max_age_days", 0))  # 0 = no expiry (reserved)

    def validate(self, password: str) -> None:
        if len(password) < self.min_length:
            raise PolicyError(f"password must be at least {self.min_length} characters")
        if self.require_mixed_case and not (
            any(c.islower() for c in password) and any(c.isupper() for c in password)
        ):
            raise PolicyError("password must include upper and lower case")
        if self.require_digit and not any(c.isdigit() for c in password):
            raise PolicyError("password must include a digit")


def generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

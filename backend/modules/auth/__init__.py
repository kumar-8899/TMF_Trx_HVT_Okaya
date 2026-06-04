"""auth module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.auth.contract import AuthContract
from modules.auth.variants.default import LocalDbAuth


@register_module(
    "auth",
    contract=AuthContract,
    contract_version=1,
    display_name="User Authentication",
)
class AuthModule:
    """Marker for the auth module; the variant carries the implementation."""


register_variant("auth", "local_db", display_name="Local DB sessions")(LocalDbAuth)

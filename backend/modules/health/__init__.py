"""health module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.health.contract import HealthContract
from modules.health.variants.default import DefaultHealth


@register_module(
    "health",
    contract=HealthContract,
    contract_version=1,
    display_name="System Health & Diagnostics",
)
class HealthModule:
    """Marker for the health module; variants carry the implementation."""


register_variant("health", "default", display_name="Default")(DefaultHealth)

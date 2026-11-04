"""okaya_tower module registration (CORE.md §2.1) — app-owned module of the Okaya HVT Testbench fork."""

from core.framework.registry import register_module, register_variant
from modules.okaya_tower.contract import OkayaTowerContract
from modules.okaya_tower.variants.default import OkayaTower


@register_module(
    "okaya_tower",
    contract=OkayaTowerContract,
    contract_version=1,
    display_name="Tower light",
)
class OkayaTowerModule:
    """Marker for the okaya_tower module; the variant carries the implementation."""


register_variant("okaya_tower", "default", display_name="relay2 green/red/buzzer stack")(OkayaTower)

"""okaya_mes module registration (CORE.md §2.1) — app-owned module of the Okaya HVT Testbench fork."""

from core.framework.registry import register_module, register_variant
from modules.okaya_mes.contract import OkayaMesContract
from modules.okaya_mes.variants.default import OkayaMes


@register_module(
    "okaya_mes",
    contract=OkayaMesContract,
    contract_version=1,
    display_name="MES (Okaya table)",
)
class OkayaMesModule:
    """Marker for the okaya_mes module; the variant carries the implementation."""


register_variant("okaya_mes", "default", display_name="Okaya legacy wide-row table")(OkayaMes)

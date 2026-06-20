"""mes module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.mes.contract import MesContract
from modules.mes.variants.default import DefaultMes


@register_module(
    "mes",
    contract=MesContract,
    contract_version=1,
    display_name="MES Interlock",
)
class MesModule:
    """Marker for the mes module; variants carry the implementation."""


register_variant("mes", "default", display_name="Default (pluggable transport)")(DefaultMes)

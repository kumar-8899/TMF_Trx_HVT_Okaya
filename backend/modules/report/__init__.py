"""report module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.report.contract import ReportContract
from modules.report.variants.standard import StandardReport


@register_module(
    "report",
    contract=ReportContract,
    contract_version=1,
    display_name="Report & Analytics",
)
class ReportModule:
    """Marker for the report module; the variant carries the implementation."""


register_variant("report", "standard", display_name="Standard")(StandardReport)

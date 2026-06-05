"""logs module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.logs.contract import LogsContract
from modules.logs.variants.db import DbLogs


@register_module(
    "logs",
    contract=LogsContract,
    contract_version=1,
    display_name="Action & Error Logs",
)
class LogsModule:
    """Marker for the logs module; the variant carries the implementation."""


register_variant("logs", "db", display_name="DB store")(DbLogs)

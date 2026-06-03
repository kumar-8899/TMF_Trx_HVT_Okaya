"""daq module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.daq.contract import DaqContract
from modules.daq.variants.default import DefaultDaq


@register_module(
    "daq",
    contract=DaqContract,
    contract_version=1,
    display_name="DAQ Instruments",
)
class DaqModule:
    """Marker for the daq module; variants carry the implementation."""


register_variant("daq", "default", display_name="Default (LabVIEW)")(DefaultDaq)

"""config module registration (CORE.md §2.1).

Station configuration centre — the cascaded "Config" menu. Holds operator-editable
sub-configs (instruments now; barcode/shift/MES later), each a scalable section.
Instrument I/O specifics are LabVIEW's; this module only captures connection
profiles and asks LabVIEW to probe them.
"""

from core.framework.registry import register_module, register_variant
from modules.config.contract import ConfigContract
from modules.config.variants.default import DefaultConfig


@register_module(
    "config",
    contract=ConfigContract,
    contract_version=1,
    display_name="Configuration",
)
class ConfigModule:
    """Marker for the config module; the variant carries the implementation."""


register_variant("config", "default", display_name="Default")(DefaultConfig)

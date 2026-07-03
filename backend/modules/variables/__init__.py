"""variables module registration (CORE.md §2.1).

The variable engine (INSTRUMENT_LIBRARY.md §5.3): names scalar signals so recipes and
the sequencer reference names, never hardware. Builds Python-owned instrument
instances from config via the instrumentlib registry and serves `variable.*` over the
bridge + a REST surface.
"""

from core.framework.registry import register_module, register_variant
from modules.variables.contract import VariablesContract
from modules.variables.variants.default import DefaultVariables


@register_module("variables", contract=VariablesContract, contract_version=1,
                 display_name="Variable Engine")
class VariablesModule:
    """Marker; the variant carries the implementation."""


register_variant("variables", "default", display_name="Default")(DefaultVariables)

"""help module registration (CORE.md §2.1).

In-app documentation: serves catalog'd markdown (user docs for everyone, developer
docs for super_admin). Source of truth is the repo docs/ tree; the same corpus will
feed the planned AI help chatbot.
"""

from core.framework.registry import register_module, register_variant
from modules.help.contract import HelpContract
from modules.help.variants.default import DefaultHelp


@register_module("help", contract=HelpContract, contract_version=1, display_name="Help & Docs")
class HelpModule:
    """Marker for the help module; the variant carries the implementation."""


register_variant("help", "default", display_name="Default")(DefaultHelp)

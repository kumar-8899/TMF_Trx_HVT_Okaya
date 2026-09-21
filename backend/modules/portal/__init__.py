"""portal module registration (CORE.md §2.1).

The in-app User Portal's server side: a library of PDFs (hardware manuals, drawings) users upload or an
app ships, with full-text search. Replaces the printed software manual together with the help module's
pages; the troubleshooting assistant and case log arrive in later releases (docs/contracts/PORTAL.md).
"""

from core.framework.registry import register_module, register_variant
from modules.portal.contract import PortalContract
from modules.portal.variants.default import DefaultPortal


@register_module("portal", contract=PortalContract, contract_version=1, display_name="User Portal")
class PortalModule:
    """Marker for the portal module; the variant carries the implementation."""


register_variant("portal", "default", display_name="Default")(DefaultPortal)

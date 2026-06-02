"""hello module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.hello.contract import HelloContract
from modules.hello.variants.default import HelloDefault


@register_module(
    "hello",
    contract=HelloContract,
    contract_version=1,
    display_name="Hello (reference)",
)
class HelloModule:
    """Marker for the hello module; variants carry the implementation."""


register_variant("hello", "default", display_name="Default")(HelloDefault)

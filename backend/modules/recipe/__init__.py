"""recipe module registration (CORE.md §2.1)."""

from core.framework.registry import register_module, register_variant
from modules.recipe.contract import RecipeContract
from modules.recipe.variants.filesystem import FilesystemRecipe


@register_module(
    "recipe",
    contract=RecipeContract,
    contract_version=1,
    display_name="Test Recipe",
)
class RecipeModule:
    """Marker for the recipe module; the variant carries the implementation."""


register_variant("recipe", "filesystem", display_name="Filesystem store")(FilesystemRecipe)

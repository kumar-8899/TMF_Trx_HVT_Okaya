from modules.recipe.registry import register_step_type


@register_step_type(type_id="group", display_name="Group", composite=True)
class GroupStepType:
    """Composite: organizational container; inner steps run sequentially."""

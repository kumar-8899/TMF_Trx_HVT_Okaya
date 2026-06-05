from modules.recipe.registry import register_step_type


@register_step_type(type_id="wait", display_name="Fixed delay", composite=False)
class WaitStepType:
    """Fixed delay."""

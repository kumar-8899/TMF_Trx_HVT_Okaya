from modules.recipe.registry import register_step_type


@register_step_type(type_id="repeat", display_name="Repeat N times", composite=True)
class RepeatStepType:
    """Composite: run inner_steps N times."""

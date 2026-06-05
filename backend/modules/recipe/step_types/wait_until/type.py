from modules.recipe.registry import register_step_type


@register_step_type(type_id="wait_until", display_name="Wait for condition",
                    composite=False, capabilities=("variable_read",))
class WaitUntilStepType:
    """Poll a variable until a condition holds or the step times out."""

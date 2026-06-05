from modules.recipe.registry import register_step_type


@register_step_type(type_id="ramp_until", display_name="Ramp until condition",
                    composite=False, capabilities=("variable_write", "variable_read"))
class RampUntilStepType:
    """Linear ramp on an output, polling a condition each step."""

from modules.recipe.registry import register_step_type


@register_step_type(type_id="set_output", display_name="Set output variable",
                    composite=False, capabilities=("variable_write",))
class SetOutputStepType:
    """Write a value to an output variable; optional settle."""

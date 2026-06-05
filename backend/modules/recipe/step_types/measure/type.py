from modules.recipe.registry import register_step_type


@register_step_type(type_id="measure", display_name="Measure & store",
                    composite=False, capabilities=("variable_read",))
class MeasureStepType:
    """Read a variable (optionally averaged) and store under the step_id."""

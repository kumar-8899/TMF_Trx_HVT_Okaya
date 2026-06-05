from modules.recipe.registry import register_step_type


@register_step_type(type_id="sweep", display_name="Parameter sweep",
                    composite=True, capabilities=("variable_write",))
class SweepStepType:
    """Composite: iterate a parameter over values/range, running inner_steps."""

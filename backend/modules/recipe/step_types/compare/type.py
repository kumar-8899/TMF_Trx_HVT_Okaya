from modules.recipe.registry import register_step_type


@register_step_type(type_id="compare", display_name="Compare to limits",
                    composite=False, capabilities=("variable_read",))
class CompareStepType:
    """Compare a live read or stored measurement to a limits envelope."""

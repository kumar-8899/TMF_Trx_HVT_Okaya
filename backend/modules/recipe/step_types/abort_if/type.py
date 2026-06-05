from modules.recipe.registry import register_step_type


@register_step_type(type_id="abort_if", display_name="Abort if condition",
                    composite=False, capabilities=("variable_read",))
class AbortIfStepType:
    """Guard: evaluate a condition once; abort the run if it holds."""

from modules.recipe.registry import register_step_type


@register_step_type(type_id="if_then_else", display_name="Conditional branch",
                    composite=True, capabilities=("variable_read",))
class IfThenElseStepType:
    """Composite: evaluate a condition once, run one of two branches."""

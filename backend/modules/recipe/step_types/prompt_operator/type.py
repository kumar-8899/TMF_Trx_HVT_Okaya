from modules.recipe.registry import register_step_type


@register_step_type(type_id="prompt_operator", display_name="Operator prompt",
                    composite=False, capabilities=("operator_prompt",))
class PromptOperatorStepType:
    """Modal prompt to the operator UI; captures the response."""

from modules.recipe.registry import register_step_type


@register_step_type(type_id="measure_and_compare", display_name="Measure & compare to limits",
                    composite=False, capabilities=("variable_read",))
class MeasureAndCompareStepType:
    """Read, optionally settle, compare, return — the common case in one step."""

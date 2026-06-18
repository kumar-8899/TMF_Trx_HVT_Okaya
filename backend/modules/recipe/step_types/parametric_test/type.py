from modules.recipe.registry import register_step_type


@register_step_type(type_id="parametric_test", display_name="Parametric test", composite=False)
class ParametricTestStepType:
    """A test authored as a flat list of {name, value, unit} parameters.

    The simplified recipe-authoring shape (RECIPE UI phase 1): the operator adds a
    test and fills a table of parameter rows; no step-type/schema picker. The
    richer step-type catalog is the phase-2 sequence editor.
    """

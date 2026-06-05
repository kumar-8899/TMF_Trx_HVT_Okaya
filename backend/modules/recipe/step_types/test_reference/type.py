from modules.recipe.registry import register_step_type


@register_step_type(type_id="test_reference", display_name="Call LabVIEW test class",
                    composite=False, capabilities=("test_class",))
class TestReferenceStepType:
    """Escape hatch: reference a registered LabVIEW test class."""

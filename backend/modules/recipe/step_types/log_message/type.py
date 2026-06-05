from modules.recipe.registry import register_step_type


@register_step_type(type_id="log_message", display_name="Log message",
                    composite=False, capabilities=("diagnostics",))
class LogMessageStepType:
    """Structured log line into the run record + diagnostics bus."""

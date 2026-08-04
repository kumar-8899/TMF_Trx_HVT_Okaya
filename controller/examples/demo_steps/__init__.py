"""demo_steps — a worked example application step-type package (PYTHON_CONTROLLER.md §7.5).

Stands in for a real app package (inverter_eol_steps, motor_tester_steps). Importing it fires
the @register_step_type decorators of its step types into the shared registry — the whole
loading mechanism a customer package uses. A real package lives in its own versioned repo and
is bundled at build; this one lives under controller/examples/ purely to exercise C10."""

from demo_steps import relay_cycle  # noqa: F401 — import registers the step type

__all__ = ["relay_cycle"]

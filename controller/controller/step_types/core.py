"""The 8 core step types (PYTHON_CONTROLLER.md §7.4) — sequencer control flow +
hardware-agnostic glue. Everything else is an application package. Limits/values/counts
come from `params`, never hardcoded (§7.3 r5). Composites run inner steps (in
`params.steps`) via `ctx.execute_child` so abort, nested deadlines, and event ordering
are carried for free."""

from __future__ import annotations

from controller.context import StepAborted
from controller.registry import register_step_type
from controller.results import INFO, Limits, Measurement, StepResult
from controller.sequencer import worst

_PRIM = "primitive"


def _cond_holds(cond: dict, value: float | None) -> bool:
    if not cond:
        return True
    if "equals" in cond:
        return value == cond["equals"]
    if "below" in cond and value is not None:
        return value < float(cond["below"])
    if "above" in cond and value is not None:
        return value > float(cond["above"])
    return True


# ---- composites -----------------------------------------------------------

@register_step_type(type_id="group", display_name="Group", composite=True, kind=_PRIM)
class Group:
    """Organisational container; status = worst child (§7.4)."""
    def execute(self, params, ctx) -> StepResult:
        s = [ctx.execute_child(step).status for step in params.get("steps", [])]
        return StepResult(status=worst(s))


@register_step_type(type_id="repeat", display_name="Repeat", composite=True, kind=_PRIM)
class Repeat:
    """Run inner steps `count` times, or until an `until` signal condition holds
    (RECIPE.md §7: an infinite repeat without a stop condition is a validation error)."""
    def execute(self, params, ctx) -> StepResult:
        n = int(params.get("count", 1))
        until = params.get("until") or {}
        statuses: list[str] = []
        prev = ctx.sequence
        try:
            for i in range(n):
                if ctx.aborted() or ctx.deadline_exceeded():
                    raise StepAborted()
                if until.get("signal") and _cond_holds(until, ctx.read(until["signal"])):
                    break
                ctx.sequence = i + 1
                for step in params.get("steps", []):
                    statuses.append(ctx.execute_child(step).status)
        finally:
            ctx.sequence = prev
        return StepResult(status=worst(statuses))


@register_step_type(type_id="sweep", display_name="Sweep", composite=True, kind=_PRIM)
class Sweep:
    """Run inner steps once per value in a list, writing that value to a named signal."""
    def execute(self, params, ctx) -> StepResult:
        signal = params["signal"]
        statuses: list[str] = []
        prev = ctx.sequence
        try:
            for i, v in enumerate(params.get("values", [])):
                if ctx.aborted() or ctx.deadline_exceeded():
                    raise StepAborted()
                ctx.write(signal, v)
                ctx.sequence = i + 1
                for step in params.get("steps", []):
                    statuses.append(ctx.execute_child(step).status)
        finally:
            ctx.sequence = prev
        return StepResult(status=worst(statuses))


@register_step_type(type_id="if", display_name="If", composite=True, kind=_PRIM)
class If:
    """Run inner steps only when a signal condition holds; skipped => PASS."""
    def execute(self, params, ctx) -> StepResult:
        cond = params.get("condition") or {}
        value = ctx.read(cond["signal"]) if cond.get("signal") else None
        if not _cond_holds(cond, value):
            return StepResult(status="PASS")
        s = [ctx.execute_child(step).status for step in params.get("steps", [])]
        return StepResult(status=worst(s))


# ---- primitives -----------------------------------------------------------

@register_step_type(type_id="wait", display_name="Wait", kind=_PRIM)
class Wait:
    """Pause a fixed duration, deadline- and abort-aware."""
    def execute(self, params, ctx) -> StepResult:
        ctx.wait(float(params.get("seconds", 0)))
        return StepResult()


@register_step_type(type_id="set_output", display_name="Set output", kind=_PRIM)
class SetOutput:
    """Write a value to a named signal. Records the written (clamped) value as INFO."""
    def execute(self, params, ctx) -> StepResult:
        written = ctx.write(params["signal"], params["value"])
        return StepResult(measurements=[
            Measurement(params["signal"], written, params.get("unit"), status=INFO)])


@register_step_type(type_id="measure_and_compare", display_name="Measure & compare", kind=_PRIM)
class MeasureAndCompare:
    """Read a signal, compare against limits, produce ONE measurement (§8)."""
    def execute(self, params, ctx) -> StepResult:
        value = ctx.read(params["signal"])
        lim = Limits(min=params.get("min"), max=params.get("max"), expected=params.get("expected"))
        name = params.get("name") or params["signal"]
        return StepResult(measurements=[Measurement(name, value, params.get("unit"), limits=lim)])


@register_step_type(type_id="prompt_operator", display_name="Prompt operator", kind=_PRIM)
class PromptOperator:
    """Halt and request an operator action/confirmation. The blocking operator-response
    channel arrives with the prompt UI (open item §Open #3); until then it records the
    prompt as INFO and continues so recipes using it validate and run in sim."""
    def execute(self, params, ctx) -> StepResult:
        ctx.diag("info", "operator prompt", prompt=params.get("message", ""))
        return StepResult(measurements=[
            Measurement("operator_prompt", params.get("message", ""), status=INFO)])

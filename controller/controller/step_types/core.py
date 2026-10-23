"""The 8 core step types (PYTHON_CONTROLLER.md §7.4) — sequencer control flow +
hardware-agnostic glue. Everything else is an application package. Limits/values/counts
come from `params`, never hardcoded (§7.3 r5). Composites run inner steps (in
`params.steps`) via `ctx.execute_child` so abort, nested deadlines, and event ordering
are carried for free."""

from __future__ import annotations

from controller.context import StepAborted
from controller.registry import register_step_type
from controller.results import FAIL, INFO, Limits, Measurement, StepResult, evaluate
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
    @staticmethod
    def bindings(params):
        sig = (params.get("until") or {}).get("signal")
        return {"signals": [sig] if sig else [], "actions": []}

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
    @staticmethod
    def bindings(params):
        return {"signals": [params["signal"]] if params.get("signal") else [], "actions": []}

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
    @staticmethod
    def bindings(params):
        sig = (params.get("condition") or {}).get("signal")
        return {"signals": [sig] if sig else [], "actions": []}

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
    @staticmethod
    def bindings(params):
        return {"signals": [params["signal"]] if params.get("signal") else [], "actions": []}

    def execute(self, params, ctx) -> StepResult:
        written = ctx.write(params["signal"], params["value"])
        return StepResult(measurements=[
            Measurement(params["signal"], written, params.get("unit"), status=INFO)])


@register_step_type(type_id="measure_and_compare", display_name="Measure & compare", kind=_PRIM)
class MeasureAndCompare:
    """Read a signal, compare against limits, produce ONE measurement (§8).

    Graded reads can be transient (a Modbus connection reset): `retries` (0–5, default 0) re-reads
    the SAME signal — no preconditions re-run, only this read — with a fixed `settle_s` pause
    between attempts (abort-aware via ctx.wait). A failed read OR an out-of-limit reading is
    re-read; ONLY the last attempt is reported. A read that still raises on the final attempt is
    the FAIL row ERROR (D5), carrying the cause. StepAborted is never retried. (D14)"""
    @staticmethod
    def bindings(params):
        return {"signals": [params["signal"]] if params.get("signal") else [], "actions": []}

    def execute(self, params, ctx) -> StepResult:
        signal = params["signal"]
        lim = Limits(min=params.get("min"), max=params.get("max"), expected=params.get("expected"))
        name = params.get("name") or signal
        unit = params.get("unit")
        attempts = max(0, min(5, int(params.get("retries", 0) or 0))) + 1
        settle_s = max(0.0, float(params.get("settle_s", 0.5) or 0.0))
        last_exc: Exception | None = None
        for i in range(attempts):
            if i > 0:
                ctx.wait(settle_s)                      # abort-aware pause before a re-read
            try:
                value = ctx.read(signal)
            except StepAborted:
                raise
            except Exception as exc:                    # noqa: BLE001 — transient read; may retry
                last_exc = exc
                continue
            m = Measurement(name, value, unit, limits=lim)
            if evaluate(m) != FAIL or i == attempts - 1:
                return StepResult(measurements=[m])     # pass, or last attempt wins
        # every attempt raised — one FAIL row ERROR with the cause (D5)
        cause = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "read failed"
        return StepResult(
            measurements=[Measurement(name, "ERROR", unit, limits=lim, status=FAIL)],
            message=f"read '{signal}' failed: {cause}")


@register_step_type(type_id="prompt_operator", display_name="Prompt operator", kind=_PRIM)
class PromptOperator:
    """Halt and request an operator action/confirmation. The blocking operator-response
    channel arrives with the prompt UI (open item §Open #3); until then it records the
    prompt as INFO and continues so recipes using it validate and run in sim."""
    def execute(self, params, ctx) -> StepResult:
        ctx.diag("info", "operator prompt", prompt=params.get("message", ""))
        return StepResult(measurements=[
            Measurement("operator_prompt", params.get("message", ""), status=INFO)])

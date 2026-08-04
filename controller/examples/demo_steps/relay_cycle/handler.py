"""relay_cycle — cycle a relay N times and check its feedback contact each cycle.

An application step type (SKILL_STEP_TYPE.md worked example). Registered with the same
decorator as the core types. Touches hardware ONLY through ctx; every limit and dwell is a
recipe parameter, never hardcoded (§7.3 r5); every measured value is a Measurement (r6);
the loop is abort- and deadline-aware (r3); a loop that never proves closure is a failure,
not a silent pass (the `else` on the `for`)."""

from __future__ import annotations

from controller.context import StepAborted, StepFailed
from controller.registry import register_step_type
from controller.results import INFO, Limits, Measurement, StepResult


@register_step_type(
    type_id="relay_cycle",
    display_name="Relay cycle endurance",
    schema_path="schema.json",
    composite=False,
    required_signals=("relay_coil", "relay_feedback"),
    required_actions=(),
)
class RelayCycle:
    def execute(self, params, ctx) -> StepResult:
        cycles = int(params["cycles"])
        on_v, off_v = params["on_value"], params["off_value"]
        settle = float(params.get("settle_s", 0.05))
        limits = Limits(min=params.get("fb_min"), max=params.get("fb_max"))
        results = [Measurement("cycles_commanded", cycles, "count", status=INFO)]
        for i in range(cycles):
            if ctx.aborted() or ctx.deadline_exceeded():
                raise StepAborted()
            ctx.write("relay_coil", on_v)
            ctx.wait(settle)
            fb = ctx.read("relay_feedback")           # a failed read raises — never a default
            results.append(Measurement("contact_closed", fb, "V", limits=limits, sequence=i + 1))
            ctx.write("relay_coil", off_v)
            ctx.wait(settle)
        else:
            if cycles <= 0:
                raise StepFailed("relay_cycle needs cycles >= 1")
        return StepResult(measurements=results)

"""hipot_acw — route a DUT tap pair through the multiplexing relays, run one AC-withstand
(hipot) test on the shared UT5320R+ tester, and judge the leakage current against a limit.

The bench's Primary/Secondary/Feedback/Core test points share ONE hipot tester; the Waveshare
relays select which pair is under test, exactly like mux_measure does for the AC meter. This
step energises the relays named in `route`, settles, invokes the tester's `measure_acw`
(`safety_tester` capability, reached via `action` — never a scalar signal), and produces TWO
measurements: the leakage current in mA (judged against `max_current_ma`) and a `breakdown`
flag (judged: must be False). Breakdown is a genuine dielectric fault (arc/short/ground-fault/
overvoltage) reported by the tester itself — distinct from a plain over-limit leakage reading,
so a low leakage current does not mask a breakdown event. It ALWAYS opens the route again in a
`finally`, so a tester error or an abort can never leave a tap connected to a live HV output
(r3/safety). Relay names, the test voltage/time/limit, and which tester program step to use are
all recipe parameters — the exact relay combination per test point is site wiring, kept as data.
"""

from __future__ import annotations

from controller.registry import register_step_type
from controller.results import Limits, Measurement, StepResult


@register_step_type(
    type_id="hipot_acw",
    display_name="Hipot AC withstand (multiplexed)",
    schema_path="schema.json",
    composite=False,
)
class HipotAcw:
    @staticmethod
    def bindings(params):
        route = list(params.get("route") or [])
        action = params.get("action") or "hipot"
        return {"signals": route, "actions": [action]}

    def execute(self, params, ctx) -> StepResult:
        route = list(params.get("route") or [])
        action = params.get("action") or "hipot"
        step = int(params.get("step", 1))
        voltage = float(params["voltage"])
        test_time = float(params["test_time"])
        settle_s = float(params.get("settle_s", 0.2))
        name = params.get("name") or "leakage_current"
        limits = Limits(max=float(params["max_current_ma"]))

        for sig in route:
            ctx.write(sig, 1)
        try:
            ctx.wait(settle_s)
            # A failed/invalid call raises — never a silent default (§7.3 rule 7).
            leakage_ma, breakdown = ctx.invoke(action, "measure_acw", [voltage, test_time, step])
            return StepResult(measurements=[
                Measurement(name, leakage_ma, "mA", limits=limits),
                Measurement(f"{name}_breakdown", breakdown, None, Limits(expected=False)),
            ])
        finally:
            for sig in route:
                ctx.write(sig, 0)

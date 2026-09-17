"""hipot_acw — route a DUT tap pair through the multiplexing relays, run one AC-withstand
(hipot) test on the shared UT5320R+ tester, and judge the leakage current against a limit.

The bench's Primary/Secondary/Feedback/Core test points share ONE hipot tester; the Waveshare
relays select which pair is under test, exactly like mux_measure does for the AC meter. Sequence:
energise the relays named in `route`, settle (`settle_s`), run the tester's `measure_acw`
(`safety_tester` capability, reached via `action` — never a scalar signal) and wait for it to
report the step complete, open the route again in a `finally` (so a tester error or an abort can
never leave a tap connected to a live HV output — r3/safety) with a settle (`settle_off_s`), then
build/judge the StepResult from measure_acw's own returned value (Python only actually hands the
return value back to the caller after `finally` runs, so validation/display already happens after
the route is open with no extra step). A driver-only `fetch_acw_result` re-query was tried
(2026-09) to explicitly re-read the result after opening the route, on the theory the tester holds
it in memory — confirmed LIVE that this is unreliable when two hipot_acw steps in one recipe
share the same tester program `step` number (the default, since neither test point overrides it):
the re-query intermittently got `GarbageResponse: step N has no completed result yet` even though
measure_acw itself had already completed cleanly. Reverted to the single trusted read; do not
reintroduce the second FETCh? query without a stable repro on real hardware. Produces TWO
measurements: the leakage current in mA (judged against `max_current_ma`) and a `breakdown` flag
(judged: must be False). Breakdown is a genuine dielectric fault (arc/short/ground-fault/
overvoltage) reported by the tester itself — distinct from a plain over-limit leakage reading, so
a low leakage current does not mask a breakdown event. Not reported as a measurement row (recipe
choice, 2026-09): a True breakdown still hard-fails the step via StepFailed instead of a silent
default (§7.3 rule 7), it just isn't listed in the report. Relay names, the test voltage/time/limit,
and which tester program step to use are all recipe parameters — the exact relay combination per
test point is site wiring, kept as data.
"""

from __future__ import annotations

import time

from controller.context import StepFailed
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
        settle_s = float(params.get("settle_s", 1.0))
        settle_off_s = float(params.get("settle_off_s", 2.0))
        off_margin_s = float(params.get("off_margin_s", 4.0))
        name = params.get("name") or "leakage_current"
        limits = Limits(max=float(params["max_current_ma"]))

        for sig in route:
            ctx.write(sig, 1)
        try:
            ctx.wait(settle_s)
            # measure_acw polls the tester's FETCh? page until the step's sorting result posts
            # (manual §1.12) -- confirmed live (2026-09) that this can post BEFORE the tester's
            # own on-screen test timer actually reaches zero (the sorting judgement is decided at
            # end of dwell, while the instrument is still ramping the HV back down through its own
            # fall time). So the FETCh? signal alone is not a safe gate for opening the route --
            # floor the closed-route time at test_time + off_margin_s (wall-clock, timer-based)
            # regardless of when measure_acw happens to return. A failed/invalid call raises —
            # never a silent default (§7.3 rule 7).
            t0 = time.monotonic()
            leakage_ma, breakdown = ctx.invoke(action, "measure_acw", [voltage, test_time, step])
            remaining = (test_time + off_margin_s) - (time.monotonic() - t0)
            if remaining > 0:
                ctx.wait(remaining)
        finally:
            for sig in route:
                ctx.write(sig, 0)
            ctx.wait(settle_off_s)

        if breakdown:
            raise StepFailed(f"{name}: genuine dielectric breakdown reported by tester")
        return StepResult(measurements=[
            Measurement(name, leakage_ma, "mA", limits=limits),
        ])

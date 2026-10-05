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
reintroduce the second FETCh? query without a stable repro on real hardware.

Produces exactly ONE measurement row per run, named by the `name` param (the recipe form passes
the human test-point label, e.g. "Primary to Secondary", so the Results table reads naturally):
the leakage current in mA, judged against `max_current_ma`. A test that FAILS is always visible
as a FAIL row, never as a missing one — this step does not raise for a test failure:
  * over-limit leakage            -> the reading, FAIL (judged by the framework from the limit);
  * dielectric breakdown reported  -> the reading, FAIL asserted explicitly (a low reading can't
    by the tester (arc/short/GFI/    mask a breakdown); the dedicated `breakdown` flag is still not
    overvoltage)                     a separate report row (recipe choice, 2026-09);
  * tester/link error or a         -> value "ERROR", FAIL (a non-numeric value against numeric
    malformed reply                  limits is a FAIL by the framework's own rule), with the error
                                     text in the step message + a diag event.
Only an operator abort (StepAborted) propagates — it is not a test outcome. The route is reopened
in every case, and its closed time is floored at test_time + off_margin_s even after a tester
error (the tester may still be applying HV when the call fails — never hot-switch the relays).
Relay names, the test voltage/time/limit, and which tester program step to use are all recipe
parameters — the exact relay combination per test point is site wiring, kept as data.
"""

from __future__ import annotations

import time

from controller.context import StepAborted
from controller.registry import register_step_type
from controller.results import FAIL, Limits, Measurement, StepResult


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

        leakage_ma = None
        breakdown = False
        error: Exception | None = None

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
            # regardless of when measure_acw happens to return, or whether it returned at all.
            t0 = time.monotonic()
            try:
                # max_current_ma is BOTH judged here and programmed on the tester (its own upper
                # current limit, FUNC:AC:UPPC) — otherwise the tester keeps its front-panel limit.
                leakage_ma, breakdown = ctx.invoke(
                    action, "measure_acw", [voltage, test_time, step, limits.max])
            except StepAborted:
                raise
            except Exception as exc:  # noqa: BLE001 — becomes a visible FAIL row, never a silent PASS
                error = exc
            remaining = (test_time + off_margin_s) - (time.monotonic() - t0)
            if remaining > 0:
                ctx.wait(remaining)
        finally:
            for sig in route:
                ctx.write(sig, 0)
            ctx.wait(settle_off_s)

        if error is not None:
            detail = f"{type(error).__name__}: {error}"
            ctx.diag("error", "hipot_acw.measure_failed", step_name=name, error=detail)
            return StepResult(
                measurements=[Measurement(name, "ERROR", "mA", limits=limits)],
                message=f"{name}: tester error — {detail}",
            )
        if breakdown:
            return StepResult(
                measurements=[Measurement(name, leakage_ma, "mA", limits=limits, status=FAIL)],
                message=f"{name}: dielectric breakdown reported by tester",
            )
        return StepResult(measurements=[Measurement(name, leakage_ma, "mA", limits=limits)])

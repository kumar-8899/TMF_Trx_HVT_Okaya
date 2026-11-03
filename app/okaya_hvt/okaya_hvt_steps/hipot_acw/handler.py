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

Before each energise the step runs a RELAY INTERLOCK (`routing_action` -> the mux card's
`open_all_verified`): drive every routing coil open and FC01 read it back, so a tap is never
closed on top of a still-live one (the confirmed two-contactors-on fault). If the safe state
cannot be proven the route is NOT energised and the row is a visible interlock FAIL. The whole
test is also retried once by default (`retries`) on any FAIL/breakdown/error — an intermittent
overlap artifact clears on the clean retry, a real fault stays FAIL. (The interlock's read-back
catches a LOST open command; a contactor that is merely slow to drop out is covered by the
inter-step dead-time `settle_off_s`.)

Produces exactly ONE measurement row per run, named by the `name` param (the recipe form passes
the human test-point label, e.g. "Primary to Secondary", so the Results table reads naturally):
the leakage current in mA, judged against `max_current_ma`. A test that FAILS is always visible
as a FAIL row, never as a missing one — this step does not raise for a test failure:
  * over-limit leakage            -> the reading, FAIL (judged by the framework from the limit);
  * dielectric breakdown reported  -> the reading, FAIL asserted explicitly (a low reading can't
    by the tester (arc/short/GFI/    mask a breakdown); the step message + a diag event name the
    overvoltage)                     tester's own token (ARC/SHORT/GFI/VOLT ERR, via
                                     last_acw_result()); still no separate report row;
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
        actions = [action]
        routing = params.get("routing_action", "routing")
        if routing and routing not in actions:
            actions.append(routing)
        return {"signals": route, "actions": actions}

    def execute(self, params, ctx) -> StepResult:
        route = list(params.get("route") or [])
        action = params.get("action") or "hipot"
        routing_action = params.get("routing_action", "routing")   # falsy disables the interlock
        step = int(params.get("step", 1))
        voltage = float(params["voltage"])
        test_time = float(params["test_time"])
        settle_s = float(params.get("settle_s", 1.0))
        settle_off_s = float(params.get("settle_off_s", 2.0))
        off_margin_s = float(params.get("off_margin_s", 4.0))
        verify_settle_s = float(params.get("verify_settle_s", 0.3))
        verify_retries = int(params.get("verify_retries", 2))
        retries = int(params.get("retries", 1))         # re-run the whole test once more on FAIL
        name = params.get("name") or "leakage_current"
        limits = Limits(max=float(params["max_current_ma"]))

        attempts = max(1, retries + 1)
        leakage_ma = breakdown = error = energized = None
        for attempt in range(1, attempts + 1):
            leakage_ma, breakdown, error, energized = self._attempt(
                ctx, route=route, action=action, routing_action=routing_action,
                voltage=voltage, test_time=test_time, step=step, limits=limits, name=name,
                settle_s=settle_s, settle_off_s=settle_off_s, off_margin_s=off_margin_s,
                verify_settle_s=verify_settle_s, verify_retries=verify_retries)
            if not self._is_fail(leakage_ma, breakdown, error, limits) or attempt == attempts:
                break
            ctx.diag("warning", "hipot_acw.retry", step_name=name, attempt=attempt,
                     reason=("interlock" if (error is not None and not energized)
                             else "error" if error is not None
                             else "breakdown" if breakdown else "over_limit"))

        return self._result(ctx, leakage_ma=leakage_ma, breakdown=breakdown, error=error,
                            energized=energized, action=action, name=name, limits=limits)

    def _attempt(self, ctx, *, route, action, routing_action, voltage, test_time, step, limits,
                 name, settle_s, settle_off_s, off_margin_s, verify_settle_s, verify_retries):
        """One full cycle: prove the mux is all-open, energise the route, measure, open again.
        Returns (leakage_ma, breakdown, error, energized). `energized` is False when the
        pre-energise interlock failed — the route was NEVER closed in that case (r3 safety)."""
        leakage_ma = None
        breakdown = False
        error: Exception | None = None

        # Interlock (r3): never energise a route on top of a live one. Drive EVERY routing coil
        # open and FC01-read it back FIRST; a coil that will not read open (a dropped OFF write
        # that left a contactor energised — the confirmed two-contactors-on fault) makes this
        # raise, and we return WITHOUT energising, as a visible ERROR/FAIL row (not a raise: a
        # raised step emits no test-result).
        if routing_action:
            try:
                ctx.invoke(routing_action, "open_all_verified", [verify_settle_s, verify_retries])
            except StepAborted:
                raise
            except Exception as exc:  # noqa: BLE001 — safe state unproven -> never energise
                ctx.diag("error", "hipot_acw.interlock_failed", step_name=name,
                         error=f"{type(exc).__name__}: {exc}")
                return None, False, exc, False
            ctx.diag("info", "hipot_acw.interlock_ok", step_name=name, route=route)

        for sig in route:
            ctx.write(sig, 1)
        # Relay actuation is a digital OUTPUT — written, never polled — so nothing about which tap
        # is energised reaches the value/ stream or the flight recorder. Emit edge diags (captured
        # in the diag/ class) so the route's ON/OFF timeline IS visible in a capture.
        ctx.diag("info", "hipot_acw.route_closed", step_name=name, route=route)
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
            ctx.diag("info", "hipot_acw.route_open", step_name=name, route=route)
            ctx.wait(settle_off_s)
        return leakage_ma, breakdown, error, True

    @staticmethod
    def _is_fail(leakage_ma, breakdown, error, limits) -> bool:
        """Mirror the framework's own PASS/FAIL rule so the retry loop can decide: an error or a
        reported breakdown is a FAIL; a non-numeric reading is a FAIL (ERROR vs numeric limits);
        otherwise it is a FAIL only when the leakage exceeds the limit."""
        if error is not None or breakdown:
            return True
        if not isinstance(leakage_ma, (int, float)):
            return True
        return leakage_ma > limits.max

    def _result(self, ctx, *, leakage_ma, breakdown, error, energized, action, name, limits):
        if error is not None:
            detail = f"{type(error).__name__}: {error}"
            if not energized:   # the interlock blocked this test — the route was never closed
                ctx.diag("error", "hipot_acw.measure_failed", step_name=name, error=detail)
                return StepResult(
                    measurements=[Measurement(name, "ERROR", "mA", limits=limits)],
                    message=f"{name}: relay interlock failed (safe state not confirmed) — {detail}",
                )
            ctx.diag("error", "hipot_acw.measure_failed", step_name=name, error=detail)
            return StepResult(
                measurements=[Measurement(name, "ERROR", "mA", limits=limits)],
                message=f"{name}: tester error — {detail}",
            )
        if breakdown:
            # The reading is the current at the instant the tester tripped (it cuts the HV), so a
            # FAIL at a low mA is expected — say WHICH trip it was (ARC / SHORT / GFI / VOLT ERR).
            reason = ""
            try:
                reason = str(ctx.invoke(action, "last_acw_result") or "")
            except StepAborted:
                raise
            except Exception:  # noqa: BLE001 — the explanation is best-effort; the FAIL stands either way
                pass
            detail = f" ({reason})" if reason else ""
            ctx.diag("warning", "hipot_acw.breakdown", step_name=name, result=reason or None,
                     leakage_ma=leakage_ma, limit_ma=limits.max)
            return StepResult(
                measurements=[Measurement(name, leakage_ma, "mA", limits=limits, status=FAIL)],
                message=(f"{name}: dielectric breakdown reported by tester{detail} — "
                         f"{leakage_ma} mA at the trip, limit {limits.max} mA"),
            )
        return StepResult(measurements=[Measurement(name, leakage_ma, "mA", limits=limits)])

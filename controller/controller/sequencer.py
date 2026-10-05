"""The sequencer — step-tree walk, dispatch, timing, verdict, event ordering
(PYTHON_CONTROLLER.md §5–§8).

Event ordering per run (§6):
    run-started -> ( step-started · step-completed · test-result )* -> (run engine emits the terminal)

The sequencer emits per-step events and returns PASS/FAIL; the run state machine
(runstate.py) owns run-started/run-finished/run-aborted + teardown. Leaf-step verdicts
are computed from measurements (§8.2); composite verdicts aggregate their children."""

from __future__ import annotations

import time

from controller import registry, results
from controller.context import StepAborted, StepContext, StepFailed


class Sequencer:
    def __init__(self, variables, emit, diag_fn):
        self._vars = variables
        self._emit = emit            # emit(event_type, payload)
        self._diag = diag_fn
        self._any_fail = False
        self._stop_on_fail = False

    def run(self, recipe: dict, *, run_id: str, station: str, run_parameters: dict,
            deadline_ts: float, aborted_fn) -> str:
        """Walk the recipe's top-level steps. Returns 'PASS' | 'FAIL'. Raises StepAborted
        if aborted (the engine then runs teardown + emits run-aborted).

        Recipe-level `stop_on_fail: true` (default false = run every step regardless): once any
        step's FINAL attempt FAILs, every later step is skipped — see `_exec`."""
        self._any_fail = False
        self._stop_on_fail = recipe.get("stop_on_fail") is True
        ctx = StepContext(
            station=station, run_id=run_id, trace=f"run:{run_id}", run_parameters=run_parameters,
            variables=self._vars, deadline_ts=deadline_ts, aborted_fn=aborted_fn,
            diag_fn=self._diag, child_runner=self._exec)
        for step in recipe.get("steps", []) or []:
            self._exec(step, ctx)
        return results.FAIL if self._any_fail else results.PASS

    def _exec(self, step: dict, ctx: StepContext) -> results.StepResult:
        if ctx.aborted():
            raise StepAborted()
        step_id = step.get("id") or step.get("type", "step")
        type_id = step.get("type")
        if self._stop_on_fail and self._any_fail:
            # An earlier step already FAILed (final attempt) and the recipe asked to stop at the
            # first failure. Skip silently: no step-started/-completed/test-result events, so the
            # event stream only ever describes steps that actually ran. The verdict is already
            # FAIL (_any_fail); teardown is the run engine's job, not this walk's, so it still
            # runs. INFO (not PASS) so a skipped child can never read as a passing one.
            self._diag("info", "step.skipped", step_id=step_id, reason="stop_on_fail")
            return results.StepResult(status=results.INFO, message="skipped: stop_on_fail")
        entry = registry.get(type_id)
        if entry is None:
            raise StepFailed(f"unknown step type '{type_id}'")   # validation should have caught it

        # Retry (§6.1): re-run a failing step while attempts remain. step-started/completed
        # fire PER attempt; test-result is emitted ONLY for the final attempt, so a flaky
        # retry is visible in the event stream but never enters the report / yield. A step
        # that passes on attempt 2 is a PASS with attempt: 2.
        attempts_allowed = int(step.get("retry_count", 0) or 0) + 1
        result = results.StepResult()
        for attempt in range(1, attempts_allowed + 1):
            if ctx.aborted():
                raise StepAborted()
            result, status = self._attempt(step, entry, ctx, step_id, type_id, attempt, attempts_allowed)
            final = status != results.FAIL or attempt == attempts_allowed
            if final:
                for m in result.measurements:
                    self._emit("test-result", {"run_id": ctx.run_id, "step_id": step_id,
                                               "attempt": attempt, "cycle_time_ms": result.elapsed_ms,
                                               **results.measurement_dict(m, step_id)})
            self._emit("step-completed", {"run_id": ctx.run_id, "step_id": step_id,
                                          "status": status, "elapsed_ms": result.elapsed_ms,
                                          "measurement_count": len(result.measurements),
                                          "message": result.message, "attempt": attempt,
                                          "attempts_allowed": attempts_allowed})
            self._diag("info", "step.end", step_id=step_id, status=status, attempt=attempt,
                       elapsed_ms=result.elapsed_ms, measurement_count=len(result.measurements))
            if final:
                if status == results.FAIL:
                    self._any_fail = True         # only the FINAL verdict counts
                return result
        return result

    def _attempt(self, step, entry, ctx, step_id, type_id, attempt, attempts_allowed):
        self._emit("step-started", {"run_id": ctx.run_id, "step_id": step_id, "step_type": type_id,
                                    "attempt": attempt, "attempts_allowed": attempts_allowed})
        self._diag("info", "step.start", step_id=step_id, step_type=type_id, attempt=attempt)
        t0 = time.monotonic()
        handler = entry.handler_cls()
        crashed = False
        try:
            result = handler.execute(step.get("params", {}) or {}, ctx) or results.StepResult()
        except StepAborted:
            raise
        except StepFailed as exc:
            crashed = True
            result = results.StepResult(status=results.FAIL, message=str(exc))
        except Exception as exc:  # noqa: BLE001 — an impossible condition fails the step (§7.3 r7)
            crashed = True
            result = results.StepResult(status=results.FAIL, message=f"{type(exc).__name__}: {exc}")

        if entry.composite:
            status = result.status                     # handler aggregated its children
        else:
            for m in result.measurements:             # stamp the loop index (sweep/repeat)
                if m.sequence is None:
                    m.sequence = ctx.sequence
            results.finalize(result.measurements)
            # A crashed step is FAIL regardless of measurements (§8.2's "empty list is PASS"
            # rule governs a NORMAL return with nothing to check, never a raised exception —
            # step_status() must not be allowed to override a status already forced FAIL by
            # a raised exception; that would silently launder a crash into a reported PASS).
            status = results.FAIL if crashed else results.step_status(result.measurements)
        result.status = status
        result.attempt = attempt
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return result, status


def worst(child_statuses: list[str]) -> str:
    """Composite aggregate: FAIL if any child FAILed (§8.2 extended to control flow)."""
    return results.FAIL if any(s == results.FAIL for s in child_statuses) else results.PASS

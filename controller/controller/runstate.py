"""Per-station run state machine + engine (PYTHON_CONTROLLER.md §5, §6).

    idle --run.start--> starting --recipe ok--> running --done--> teardown --> idle
                            |  fetch/validate fail      | abort/deadline
                            v                           v
                        (run-aborted, idle)         aborting -> teardown -> (idle | faulted)

Invariants: run.start accepted only in idle; exactly one terminal event per run
(run-finished | run-aborted); teardown always runs on a normal abort (safety trip skips
it — that's C7); a step past its deadline + grace faults the station and is abandoned,
never killed (§5.4)."""

from __future__ import annotations

import threading
import time
import uuid

from controller.context import StepAborted
from controller.sequencer import Sequencer

IDLE, STARTING, RUNNING, ABORTING, TEARDOWN, FAULTED = \
    "idle", "starting", "running", "aborting", "teardown", "faulted"

_DEFAULT_TIMEOUT_MS = 300_000


class RunEngine:
    def __init__(self, station: str, *, variables, emit, recipe_fetch, safe_state, diag,
                 abort_grace_ms: int = 2000, teardown_timeout_ms: int = 30000):
        self.station = station
        self._vars = variables
        self._emit = emit                      # emit(event_type, payload)
        self._recipe_fetch = recipe_fetch      # (recipe_id, version) -> recipe dict (may raise)
        self._safe_state = safe_state          # () -> apply safe_state to this station's instances
        self._diag = diag
        self._grace = abort_grace_ms / 1000
        self._teardown_timeout = teardown_timeout_ms / 1000

        self.state = IDLE
        self.run_id: str | None = None
        self._abort = threading.Event()
        self._abort_reason = ""
        self._deadline = 0.0
        self._thread: threading.Thread | None = None
        self._watchdog: threading.Timer | None = None

    # ---- served ops (called on the MQTT thread) --------------------------

    def start(self, body: dict) -> dict:
        if self.state != IDLE:
            return {"accepted": False, "error": _refusal(self.state)}
        run_id = (body or {}).get("run_id") or uuid.uuid4().hex   # app mints; controller echoes
        self.run_id = run_id
        self.state = STARTING
        self._abort.clear()
        self._abort_reason = ""
        self._thread = threading.Thread(target=self._run, args=(run_id, dict(body or {})),
                                        name=f"run-{self.station}", daemon=True)
        self._thread.start()
        return {"run_id": run_id, "accepted": True}

    def abort(self) -> dict:
        if self.state in (STARTING, RUNNING):
            self._abort_reason = "operator_abort"
            self._abort.set()
            self.state = ABORTING
        return {"ok": True}

    # ---- the run thread --------------------------------------------------

    def _run(self, run_id: str, body: dict) -> None:
        recipe_id = body.get("recipe_id")
        try:
            recipe = self._recipe_fetch(recipe_id, body.get("version"))
        except Exception as exc:  # noqa: BLE001
            self._terminal("run-aborted", {"run_id": run_id, "reason": "recipe_fetch_failed",
                                           "detail": str(exc)})
            self.state = IDLE
            return
        errors = _validate(recipe)
        if errors:
            self._terminal("run-aborted", {"run_id": run_id, "reason": "validation_failed",
                                           "errors": errors})
            self.state = IDLE
            return

        self.state = RUNNING
        timeout = (recipe.get("timeout_ms") or _DEFAULT_TIMEOUT_MS) / 1000
        self._deadline = time.monotonic() + timeout
        self._arm_watchdog(timeout + self._grace)
        self._emit("run-started", {"run_id": run_id, "recipe_id": recipe_id})
        seq = Sequencer(self._vars, self._emit, self._diag)
        try:
            result = seq.run(recipe, run_id=run_id, station=self.station,
                             run_parameters=body.get("run_parameters") or {},
                             deadline_ts=self._deadline, aborted_fn=self._abort.is_set)
        except StepAborted:
            self._disarm_watchdog()
            timed_out = time.monotonic() >= self._deadline
            reason = "step_timeout" if timed_out else (self._abort_reason or "operator_abort")
            self._teardown()
            self._terminal("run-aborted", {"run_id": run_id, "reason": reason})
            self.state = FAULTED if timed_out else IDLE
            return
        except Exception as exc:  # noqa: BLE001 — sequencer malfunction, not a DUT fail
            self._disarm_watchdog()
            self._teardown()
            self._terminal("run-aborted", {"run_id": run_id, "reason": "error", "detail": str(exc)})
            self.state = FAULTED
            return
        self._disarm_watchdog()
        self._teardown()
        self._terminal("run-finished", {"run_id": run_id, "result": result})
        self.state = IDLE

    # ---- teardown + watchdog ---------------------------------------------

    def _teardown(self) -> None:
        self.state = TEARDOWN
        try:
            self._safe_state()
        except Exception as exc:  # noqa: BLE001 — teardown must not raise past here
            self._diag("error", "teardown failed", station=self.station, error=str(exc))

    def _arm_watchdog(self, secs: float) -> None:
        self._watchdog = threading.Timer(secs, self._watchdog_fire)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _disarm_watchdog(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None

    def _watchdog_fire(self) -> None:
        # A handler that ignored ctx and is still running past deadline+grace: signal
        # abort so a cooperative handler unwinds; if it never returns the thread is
        # abandoned (§5.4) — the station is faulted and other stations keep running.
        if self.state in (RUNNING, ABORTING):
            self._abort_reason = "step_timeout"
            self._abort.set()

    def _terminal(self, etype: str, payload: dict) -> None:
        self._emit(etype, payload)


def _refusal(state: str) -> str:
    return {ABORTING: "run_active", RUNNING: "run_active", STARTING: "run_active",
            FAULTED: "station_faulted", TEARDOWN: "run_active"}.get(state, "run_active")


def _validate(recipe: dict) -> list[str]:
    """Cheap structural validation: every step type is registered (§7.1). Signal/action
    existence checks fold in with the station map + dry-run (C8)."""
    from controller import registry
    errors: list[str] = []

    def walk(steps):
        for s in steps or []:
            t = s.get("type")
            if registry.get(t) is None:
                errors.append(f"unknown step type '{t}'")
            walk((s.get("params") or {}).get("steps"))

    walk(recipe.get("steps"))
    return errors

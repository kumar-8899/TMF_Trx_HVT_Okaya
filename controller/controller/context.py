"""StepContext — the ONLY surface a handler touches (PYTHON_CONTROLLER.md §7.2/§7.3).

No instrument, no instance id, no bridge, no MQTT, no database. read/write/invoke resolve
against the calling station's variable map, so one handler serves every station with zero
branching. wait/aborted/deadline make every handler abort- and deadline-aware."""

from __future__ import annotations

import time
from collections.abc import Callable


class StepAborted(Exception):
    """Raised by ctx on the first call after an abort/deadline; unwinds the step tree."""


class StepFailed(Exception):
    """A handler asserting an impossible condition (§7.3 rule 7). Fails the step."""


class StepContext:
    def __init__(self, *, station: str, run_id: str, trace: str, run_parameters: dict,
                 variables, deadline_ts: float, aborted_fn: Callable[[], bool],
                 diag_fn: Callable[..., None], child_runner: Callable):
        self.station = station
        self.run_id = run_id
        self.trace = trace
        self.run_parameters = dict(run_parameters or {})
        self._vars = variables
        self._deadline_ts = deadline_ts
        self._aborted_fn = aborted_fn
        self._diag_fn = diag_fn
        self._child_runner = child_runner
        self.sequence: int | None = None    # set by repeat/sweep so loop measurements don't collide

    # ---- variable engine (calling station's map) --------------------------

    def read(self, name: str) -> float:
        return self._vars.read(name)["value"]

    def write(self, name: str, value: float) -> float:
        return self._vars.write(name, value)["written"]

    def read_many(self, names: list[str]) -> dict:
        return {n: self._vars.read(n)["value"] for n in names}

    def invoke(self, action: str, method: str, args=None):
        # Non-scalar actions arrive in C9; expose the seam now so handlers compile.
        raise NotImplementedError("ctx.invoke (non-scalar actions) lands in C9")

    # ---- timing / abort ---------------------------------------------------

    def aborted(self) -> bool:
        return bool(self._aborted_fn())

    def deadline_exceeded(self) -> bool:
        return time.monotonic() >= self._deadline_ts

    def remaining_ms(self) -> int:
        return max(0, int((self._deadline_ts - time.monotonic()) * 1000))

    def wait(self, seconds: float) -> None:
        """Deadline- and abort-aware sleep. Raises StepAborted if aborted mid-wait."""
        end = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < end:
            if self.aborted():
                raise StepAborted()
            time.sleep(min(0.02, end - time.monotonic()))

    # ---- diagnostics + composites ----------------------------------------

    def diag(self, level: str, message: str, **fields) -> None:
        self._diag_fn(level, message, **fields)

    def execute_child(self, step: dict):
        """Composites only: run an inner step through the same walker (abort + events
        + nested deadlines carried)."""
        return self._child_runner(step, self)

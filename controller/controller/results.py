"""Measurement / StepResult shapes + the verdict rule (PYTHON_CONTROLLER.md §8).

A step returns a **list** of measurements, always. The **sequencer** — not the handler
— computes the step verdict: a step FAILs if any measurement FAILs. A measurement with
no limits, or status INFO, is recorded but excluded from pass/fail. This makes it
structurally impossible to report PASS over a failed measurement (§8.2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

PASS, FAIL, INFO = "PASS", "FAIL", "INFO"


@dataclass
class Limits:
    min: float | None = None
    max: float | None = None
    expected: float | bool | str | None = None


@dataclass
class Measurement:
    name: str
    value: float | bool | str
    unit: str | None = None
    limits: Limits | None = None
    status: str | None = None          # None -> computed from limits by the sequencer
    sequence: int | None = None        # disambiguates repeated measurements in a loop


@dataclass
class StepResult:
    status: str = PASS                 # computed by the sequencer, not the handler
    measurements: list[Measurement] = field(default_factory=list)
    message: str | None = None
    elapsed_ms: int = 0
    attempt: int = 1


def evaluate(m: Measurement) -> str:
    """A measurement's own verdict. Explicit INFO or absent limits => INFO (context,
    not pass/fail). Otherwise compare the value against min/max/expected."""
    if m.status == INFO or m.limits is None:
        return INFO
    if m.status in (PASS, FAIL):
        return m.status                # handler asserted it explicitly
    lim = m.limits
    v = m.value
    if lim.expected is not None:
        return PASS if v == lim.expected else FAIL
    try:
        x = float(v)
    except (TypeError, ValueError):
        return FAIL                    # non-numeric against numeric limits is a fail, not a value
    if lim.min is not None and x < float(lim.min):
        return FAIL
    if lim.max is not None and x > float(lim.max):
        return FAIL
    return PASS


def finalize(measurements: list[Measurement]) -> list[Measurement]:
    """Stamp each measurement's computed status in place; return the list."""
    for m in measurements:
        m.status = evaluate(m)
    return measurements


def step_status(measurements: list[Measurement]) -> str:
    """FAIL if any measurement FAILed; else PASS (§8.2). An empty list is PASS."""
    return FAIL if any(m.status == FAIL for m in measurements) else PASS


def measurement_dict(m: Measurement, step_id: str) -> dict:
    """Wire shape for a test-result event / report row (fully-qualified name, §8.3)."""
    d = asdict(m)
    d["test_name"] = f"{step_id}.{m.name}"
    d["result"] = m.status
    return d

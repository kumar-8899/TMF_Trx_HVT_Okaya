"""relay_cycle scenarios (SKILL_STEP_TYPE.md §Simulation): nominal, out-of-limit,
non-responsive, aborted, and a boundary case — the mandatory minimum before review.

The sequencer computes the verdict (§8.2), so these compute it the same way (finalize +
step_status) rather than trusting any status the handler returned."""

import pytest

from controller.context import StepAborted
from controller.results import finalize, step_status
from demo_steps.relay_cycle.handler import RelayCycle
from demo_steps.relay_cycle.simulate import SCENARIOS, FakeRelay

_PARAMS = {"cycles": 5, "on_value": 1, "off_value": 0, "fb_min": 0.5, "fb_max": 1.5, "settle_s": 0}


class _Ctx:
    def __init__(self, relay, abort=False):
        self.relay, self._abort = relay, abort
        self.station, self.run_id, self.trace, self.run_parameters = "st1", "r", "t", {}
        self.sequence = None

    def read(self, name):
        assert name == "relay_feedback"
        return self.relay.read_feedback()

    def write(self, name, value):
        assert name == "relay_coil"
        self.relay.write_coil(value)
        return value

    def wait(self, s):
        pass

    def aborted(self):
        return self._abort

    def deadline_exceeded(self):
        return False


def _verdict(relay):
    result = RelayCycle().execute(_PARAMS, _Ctx(relay))
    finalize(result.measurements)
    return step_status(result.measurements)


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_scenarios(scenario):
    kwargs, expected, _ = SCENARIOS[scenario]
    assert _verdict(FakeRelay(**kwargs)) == expected


def test_nominal_records_a_measurement_per_cycle():
    result = RelayCycle().execute(_PARAMS, _Ctx(FakeRelay(closed_v=1.0)))
    contacts = [m for m in result.measurements if m.name == "contact_closed"]
    assert len(contacts) == 5 and [m.sequence for m in contacts] == [1, 2, 3, 4, 5]


def test_abort_raises_and_leaves_no_verdict():
    with pytest.raises(StepAborted):
        RelayCycle().execute(_PARAMS, _Ctx(FakeRelay(), abort=True))

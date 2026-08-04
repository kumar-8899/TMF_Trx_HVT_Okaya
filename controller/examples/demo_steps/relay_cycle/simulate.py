"""Simulated relay for reviewing the relay_cycle handler (SKILL_STEP_TYPE.md §Simulation).

The circular check: the ENGINEER supplies the behavioural numbers from the relay datasheet —
this file only wires simulation code around them. The values below are PLACEHOLDER example
numbers, NOT a spec; a real package cites its datasheet here and gets the numbers from the
engineer. Failure modes are mandatory (a sim that only models a good part proves nothing), so
this models a good part, a high-resistance/degraded contact, and a dead-open contact — each
observable through the feedback the handler reads while the coil is energised."""

from __future__ import annotations


class FakeRelay:
    """closed_v: feedback voltage read while energised and the contact has made.
    open_v: feedback while released. open_forever: the contact never makes."""

    def __init__(self, *, closed_v=1.0, open_v=0.0, open_forever=False):
        self.closed_v = closed_v
        self.open_v = open_v
        self.open_forever = open_forever
        self._coil = 0.0

    def write_coil(self, v):
        self._coil = v

    def read_feedback(self):
        if self.open_forever or not self._coil:
            return self.open_v
        return self.closed_v


# scenario -> (FakeRelay kwargs, expected step verdict, note). fb limits in the recipe are
# [fb_min=0.5, fb_max=1.5]; these numbers are the example DUT spec.
SCENARIOS = {
    "nominal":           (dict(closed_v=1.0), "PASS", "closes cleanly at 1.0 V every cycle"),
    "high_resistance":   (dict(closed_v=2.0), "FAIL", "contact makes but feedback above fb_max"),
    "dead_open":         (dict(open_forever=True), "FAIL", "never reaches fb_min"),
    "boundary_on_limit": (dict(closed_v=1.5), "PASS", "fb exactly at fb_max resolves PASS (<=)"),
}

"""Run-control errors (shared by the variant + the router, so neither imports the other)."""

from __future__ import annotations


class RunError(Exception):
    """Bad run request (unknown/missing station). -> HTTP 422."""


class RunActiveError(Exception):
    """That station already has a run in progress (MULTI_STATION.md §4.1). -> HTTP 409."""

    def __init__(self, station: str, run_id: str) -> None:
        super().__init__(f"run_active: station '{station}' is running {run_id}")
        self.station = station
        self.run_id = run_id

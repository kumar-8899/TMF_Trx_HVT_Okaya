"""Safety monitors as data + blast-radius resolution (PYTHON_CONTROLLER.md §10.1, §10.2).

A monitor is a trip source with a declared scope; the trip *detector* is product-specific
(ramp/OVP/over-temp live in app steps, §7.4) — the controller owns only the mechanism. Not
every trip source is an instrument (an E-stop belongs to none), so the blast radius is
*declared*, not inferred, and resolved once at config load from the static instrument map —
never from who currently holds what, so a station about to use a tripped resource cannot walk
into it (§10.2)."""

from __future__ import annotations

from dataclasses import dataclass

VALID_SCOPES = ("pc", "station", "resource")


class SafetyConfigError(Exception):
    """A malformed monitor, or one pointing at an unknown station/resource. Loud (§6)."""


@dataclass(frozen=True)
class Monitor:
    id: str
    scope: str
    station: str | None = None
    resource: str | None = None


@dataclass(frozen=True)
class Radius:
    """The blast radius of one monitor: which sockets abort, which instances get cut."""
    monitor_id: str
    scope: str
    stations: list[str]
    instances: list[str]


def parse_monitors(raw: list[dict] | None) -> list[Monitor]:
    monitors: list[Monitor] = []
    seen: set[str] = set()
    for i, m in enumerate(raw or []):
        mid = (m or {}).get("id")
        if not mid:
            raise SafetyConfigError(f"safety_monitors[{i}] missing 'id'")
        if mid in seen:
            raise SafetyConfigError(f"duplicate safety monitor id '{mid}'")
        scope = (m or {}).get("scope")
        if scope not in VALID_SCOPES:
            raise SafetyConfigError(f"monitor '{mid}': scope must be one of {VALID_SCOPES}")
        if scope == "station" and not m.get("station"):
            raise SafetyConfigError(f"monitor '{mid}': scope 'station' needs 'station'")
        if scope == "resource" and not m.get("resource"):
            raise SafetyConfigError(f"monitor '{mid}': scope 'resource' needs 'resource'")
        seen.add(mid)
        monitors.append(Monitor(id=mid, scope=scope,
                                station=m.get("station"), resource=m.get("resource")))
    return monitors


class SafetyMap:
    """Precomputes each monitor's blast radius from the static map. `instrument_stations`
    maps instance id -> the sockets it serves (serve-all already expanded to every station,
    as the no-lease check receives it), so a shared instrument is not cut by a single-station
    trip."""

    def __init__(self, monitors: list[Monitor], all_stations: list[str],
                 instrument_stations: dict[str, list[str]]) -> None:
        self._all = list(all_stations)
        self._inst = {k: list(v) for k, v in (instrument_stations or {}).items()}
        self._monitors = {m.id: m for m in monitors}
        self._validate()
        self._radius = {m.id: self._resolve(m) for m in monitors}

    def _validate(self) -> None:
        allset = set(self._all)
        for m in self._monitors.values():
            if m.scope == "station" and m.station not in allset:
                raise SafetyConfigError(f"monitor '{m.id}': station '{m.station}' is not configured")
            if m.scope == "resource" and m.resource not in self._inst:
                raise SafetyConfigError(f"monitor '{m.id}': resource '{m.resource}' is not an instrument")

    def _resolve(self, m: Monitor) -> Radius:
        if m.scope == "pc":
            stations = list(self._all)
            instances = list(self._inst.keys())                    # everything on the PC
        elif m.scope == "station":
            stations = [m.station]
            # only instruments serving THIS socket exclusively — never a shared one (§9.3)
            instances = [i for i, st in self._inst.items() if st and set(st) <= {m.station}]
        else:  # resource
            stations = list(self._inst.get(m.resource) or self._all)
            instances = [m.resource]
        return Radius(monitor_id=m.id, scope=m.scope, stations=stations, instances=instances)

    def monitor_ids(self) -> list[str]:
        return list(self._monitors)

    def radius(self, monitor_id: str) -> Radius | None:
        return self._radius.get(monitor_id)

    def describe(self) -> list[dict]:
        return [{"id": r.monitor_id, "scope": r.scope, "stations": r.stations,
                 "resources": r.instances} for r in self._radius.values()]

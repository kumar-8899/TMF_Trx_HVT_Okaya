"""Load + validate the one controller config file (PYTHON_CONTROLLER.md §4).

The controller self-configures from this file at startup and does not require the app
to be reachable. C1 needs only the broker + station list; later slices read the
instrument, safety, and step-type-package sections (validated leniently here so an
early config does not have to carry them)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Config missing, unreadable, or structurally invalid. Loud (PRINCIPLES §6)."""


@dataclass(frozen=True)
class StationCfg:
    station: str
    variable_map: str | None = None


@dataclass(frozen=True)
class ControllerConfig:
    broker_host: str
    broker_port: int
    stations: list[StationCfg]
    instruments: list[dict] = field(default_factory=list)
    library_paths: list[str] = field(default_factory=list)
    library_packages: list[str] = field(default_factory=list)
    daq: dict = field(default_factory=dict)
    safety_monitors: list[dict] = field(default_factory=list)
    step_type_packages: list[str] = field(default_factory=list)
    step_type_paths: list[str] = field(default_factory=list)
    simulation: bool = False
    abort_grace_ms: int = 2000
    teardown_timeout_ms: int = 30000
    raw: dict = field(default_factory=dict)


def load_config(path: str | Path) -> ControllerConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"controller config not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{p.name} is not valid JSON: {exc}") from exc
    return parse_config(data)


def parse_config(data: dict) -> ControllerConfig:
    if data.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    broker = data.get("broker") or {}
    host = broker.get("host", "127.0.0.1")
    port = int(broker.get("port", 1883))

    raw_stations = data.get("stations")
    if not isinstance(raw_stations, list) or not raw_stations:
        raise ConfigError("stations must be a non-empty list")
    stations: list[StationCfg] = []
    seen: set[str] = set()
    for i, s in enumerate(raw_stations):
        sid = (s or {}).get("station")
        if not sid:
            raise ConfigError(f"stations[{i}] missing 'station'")
        if sid in seen:
            raise ConfigError(f"duplicate station id '{sid}'")
        seen.add(sid)
        stations.append(StationCfg(station=sid, variable_map=(s or {}).get("variable_map")))

    return ControllerConfig(
        broker_host=host, broker_port=port, stations=stations,
        instruments=list(data.get("instruments", []) or []),
        library_paths=list(data.get("library_paths", []) or []),
        library_packages=list(data.get("library_packages", []) or []),
        daq=dict(data.get("daq", {}) or {}),
        safety_monitors=list(data.get("safety_monitors", []) or []),
        step_type_packages=list(data.get("step_type_packages", []) or []),
        step_type_paths=list(data.get("step_type_paths", []) or []),
        simulation=bool(data.get("simulation", False)),
        abort_grace_ms=int(data.get("abort_grace_ms", 2000)),
        teardown_timeout_ms=int(data.get("teardown_timeout_ms", 30000)),
        raw=data,
    )

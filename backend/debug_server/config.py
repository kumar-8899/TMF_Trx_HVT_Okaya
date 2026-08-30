"""Debug Server configuration (DEBUG_SERVER.md §12.4 + REMOTE_DEBUG.md §6).

Standalone: reads the `debug` block from the core's `app.json` (so a developer just
launches it), with env overrides on top for dev. No license, no activation gate.

REMOTE_DEBUG.md adds the bench↔laptop surface: an explicit `bind_host` (never
`0.0.0.0`), a static `token` validated by the sidecar itself, and the rolling /
snapshot / analog / digital / limits sub-config that the sink + discipline consume.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "app.json"
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def _load_app_json() -> dict:
    try:
        return json.loads(_DEFAULT_CONFIG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — standalone tool: fall back, never crash on boot
        return {}


def _station_of(app_json: dict) -> str:
    # app.json migrated singular `station` → `stations: [...]` (MULTI_STATION.md §1).
    return app_json.get("station") or (app_json.get("stations") or ["st1"])[0]


def _sub(cls, data: dict | None):
    """Build a sub-config dataclass from a dict, ignoring unknown keys."""
    if not data:
        return cls()
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class RollingConfig:
    enabled: bool = True
    dir: str = "data/debug"
    max_file_mb: int = 64
    max_total_mb: int = 2048
    compress_rotated: bool = True
    retention_days: int | None = None


@dataclass
class SnapshotConfig:
    enabled: bool = True
    pre_seconds: int = 30
    post_seconds: int = 5
    max_per_hour: int = 6
    include_streams: bool = False   # normative: raw stream/# is never buffered/flushed


@dataclass
class AnalogConfig:
    default_deadband_pct: float = 1.0
    summary_interval_run_s: float = 1.0
    summary_interval_idle_s: float = 2.0


@dataclass
class DigitalConfig:
    heartbeat_s: float = 60.0
    chatter_threshold: int = 20
    chatter_window_ms: int = 1000


@dataclass
class LimitsConfig:
    queue_size: int = 20_000
    repeat_collapse: bool = True
    per_type_rate_per_s: int = 200


@dataclass
class DebugConfig:
    station: str = ""
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    core_url: str = "http://127.0.0.1:8000"   # for /auth/me + the /diag/level relay
    bind_host: str = "127.0.0.1"              # REMOTE_DEBUG §3.1 — explicit iface, never 0.0.0.0
    port: int = 8001                          # the sidecar's own REST+WS port
    token: str | None = None                  # REMOTE_DEBUG §3.2 — static, sidecar-validated
    ring_capacity: int = 50_000               # §6 bounded lossless window
    orphan_timeout_s: float = 5.0             # §5.3 request→reply deadline
    require_auth: bool = True                  # dev flag; TMF_DEBUG_NO_AUTH=1 disables
    rolling: RollingConfig = field(default_factory=RollingConfig)
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    analog: AnalogConfig = field(default_factory=AnalogConfig)
    digital: DigitalConfig = field(default_factory=DigitalConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)

    # --- construction ------------------------------------------------------

    @classmethod
    def from_app_json(cls, app_json: dict | None = None) -> "DebugConfig":
        """Build from an `app.json` dict's `debug` block (no env). Used by tests."""
        aj = app_json if app_json is not None else _load_app_json()
        dbg = aj.get("debug") or {}
        cfg = cls(
            station=_station_of(aj),
            broker_host=dbg.get("broker_host", "127.0.0.1"),
            broker_port=int(dbg.get("broker_port", 1883)),
            core_url=dbg.get("core_url", "http://127.0.0.1:8000"),
            bind_host=dbg.get("bind_host", "127.0.0.1"),
            port=int(dbg.get("port", 8001)),
            token=dbg.get("token"),
            ring_capacity=int(dbg.get("ring_capacity", 50_000)),
            orphan_timeout_s=float(dbg.get("orphan_timeout_s", 5.0)),
        )
        cfg.rolling = _sub(RollingConfig, dbg.get("rolling"))
        cfg.snapshot = _sub(SnapshotConfig, dbg.get("snapshot"))
        cfg.analog = _sub(AnalogConfig, dbg.get("analog"))
        cfg.digital = _sub(DigitalConfig, dbg.get("digital"))
        cfg.limits = _sub(LimitsConfig, dbg.get("limits"))
        return cfg

    @classmethod
    def from_env(cls) -> "DebugConfig":
        """The runtime entrypoint: `app.json` `debug` block + env overrides on top."""
        cfg = cls.from_app_json()
        e = os.environ.get
        cfg.station = e("TMF_STATION") or cfg.station
        cfg.broker_host = e("TMF_BROKER_HOST", cfg.broker_host)
        cfg.broker_port = int(e("TMF_BROKER_PORT", str(cfg.broker_port)))
        cfg.core_url = e("TMF_CORE_URL", cfg.core_url)
        cfg.bind_host = e("TMF_DEBUG_BIND", cfg.bind_host)
        cfg.port = int(e("TMF_DEBUG_PORT", str(cfg.port)))
        cfg.token = e("TMF_DEBUG_TOKEN") or cfg.token
        cfg.ring_capacity = int(e("TMF_DEBUG_RING", str(cfg.ring_capacity)))
        if e("TMF_DEBUG_NO_AUTH") == "1":
            cfg.require_auth = False
        return cfg

    # --- guard -------------------------------------------------------------

    def is_loopback(self) -> bool:
        return self.bind_host in _LOOPBACK

    def validate(self) -> None:
        """Refuse an unsafe bind (REMOTE_DEBUG §0/§3.1/§3.2/§13.1). Raises ValueError.

        - `0.0.0.0` is never legal — a bench has multiple NICs; bind one explicitly.
        - A non-loopback bind with no static token is an unauthenticated remote
          surface — refuse to start rather than expose it.
        """
        if self.bind_host == "0.0.0.0":  # noqa: S104 — the value we explicitly forbid
            raise ValueError(
                "debug.bind_host must be an explicit interface address, not 0.0.0.0 "
                "(a bench has multiple NICs; bind the one you mean)")
        if not self.is_loopback() and not self.token:
            raise ValueError(
                f"debug.token is required to bind the non-loopback interface {self.bind_host!r} "
                "(no unauthenticated remote debug surface, ever)")

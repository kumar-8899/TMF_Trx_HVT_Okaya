"""Debug Server configuration (DEBUG_SERVER.md §12.4).

Standalone: env-overridable, with the station read from the core's app.json so a
developer just launches it. No license, no activation gate.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "app.json"


def _station_from_config() -> str:
    try:
        return json.loads(_DEFAULT_CONFIG.read_text(encoding="utf-8")).get("station", "st1")
    except Exception:  # noqa: BLE001 — standalone tool: fall back, never crash on boot
        return "st1"


@dataclass
class DebugConfig:
    station: str = ""
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    core_url: str = "http://127.0.0.1:8000"   # for /auth/me token validation
    port: int = 8001                          # the sidecar's own REST+WS port
    ring_capacity: int = 50_000               # §6 bounded lossless window
    orphan_timeout_s: float = 5.0             # §5.3 request→reply deadline
    require_auth: bool = True                  # dev flag; --no-auth disables

    @classmethod
    def from_env(cls) -> "DebugConfig":
        return cls(
            station=os.environ.get("TMF_STATION") or _station_from_config(),
            broker_host=os.environ.get("TMF_BROKER_HOST", "127.0.0.1"),
            broker_port=int(os.environ.get("TMF_BROKER_PORT", "1883")),
            core_url=os.environ.get("TMF_CORE_URL", "http://127.0.0.1:8000"),
            port=int(os.environ.get("TMF_DEBUG_PORT", "8001")),
            ring_capacity=int(os.environ.get("TMF_DEBUG_RING", "50000")),
            require_auth=os.environ.get("TMF_DEBUG_NO_AUTH") != "1",
        )

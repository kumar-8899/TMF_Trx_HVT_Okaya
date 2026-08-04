"""DAQ sample sources (PYTHON_CONTROLLER.md §9.5). The sim source generates plausible
AI waveforms + DI toggles so streaming, CI, and recipe demos run headless; the real
source lazy-imports nidaqmx (Windows/hardware only) exactly like the VISA/Modbus seam."""

from __future__ import annotations

import math
import random
import time


def default_channels(signal: str, n: int = 1) -> list[str]:
    prefix = "ai" if signal == "ai" else "di"
    return [f"{prefix}{i}" for i in range(n)]


def _channel_list(signal: str, channels) -> list[str]:
    if channels is None:
        return default_channels(signal, 1)
    if isinstance(channels, int):
        return default_channels(signal, channels)
    if isinstance(channels, str) and channels.isdigit():
        return default_channels(signal, int(channels))
    return list(channels)


class SimDaqSource:
    """Deterministic-ish fake: AI ~ a slow sine + noise, DI ~ a 1 Hz square."""

    def read(self, signal: str, channels: list[str]) -> dict:
        t = time.time()
        if signal == "ai":
            return {c: round(math.sin(t * 2 + i) + random.uniform(-0.02, 0.02), 4)
                    for i, c in enumerate(channels)}
        return {c: bool(int(t) % 2) for c in channels}


class NiDaqSource:
    """Real hardware. Lazy-imports nidaqmx so the module imports without it."""

    def __init__(self, params: dict | None = None):
        self._params = params or {}

    def read(self, signal: str, channels: list[str]) -> dict:
        import nidaqmx  # noqa: F401 — lazy; raises if the driver/lib is absent
        raise NotImplementedError("nidaqmx AI/DI read wiring lands with hardware validation")


def make_source(simulated: bool, params: dict | None = None):
    return SimDaqSource() if simulated else NiDaqSource(params)

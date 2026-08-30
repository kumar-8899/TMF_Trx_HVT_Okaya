"""Diagnostics bus (CORE.md §1, LOGGING.md §2.4).

The cross-language spine: LabVIEW and Python emit the same event shape, so a bug
across the MQTT seam reads as one timeline (PRINCIPLES §6). The wire shape is
fixed by LABVIEW_BRIDGE.md §4; we add `station`/`source_version` so each record
is self-contained and RAG-ready (PRINCIPLES §5).

Sinks are pluggable callables. P2 ships a JSONL sink and a stdout sink. P4 adds
an MQTT sink that publishes to the `diag` topic.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# 5 levels, aligned across the diag bus, the logs module (LEVEL_ORDER), and the Debug
# Server (which already assumes `critical`). REMOTE_DEBUG.md §3.5 / §6 level control.
LEVELS = ("debug", "info", "warning", "error", "critical")
_LEVEL_INDEX = {lv: i for i, lv in enumerate(LEVELS)}
Sink = Callable[[dict], None]


def stdout_sink(event: dict) -> None:
    print(json.dumps(event), file=sys.stdout, flush=True)


class JsonlSink:
    """Append-only JSONL file — part of the future RAG corpus (PRINCIPLES §5)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")


class BusDiagSink:
    """Mirror every diag event onto the bus at `diag/<subsystem>` via the Bridge
    (DEBUG_SERVER.md §0/§3) so the Debug Server can capture Python diagnostics on
    the same timeline as LabVIEW's. Fire-and-forget; never blocks the emitter."""

    def __init__(self, bridge) -> None:
        self._bridge = bridge

    def __call__(self, event: dict) -> None:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop (sync path / tests) — skip silently
        loop.create_task(self._publish(event))

    async def _publish(self, event: dict) -> None:
        try:
            # PC-wide diag mirror — published on the first station's topic; the Debug
            # Server subscribes tmf/+/diag (MULTI_STATION.md §5).
            station = self._bridge.stations[0]
            await self._bridge.publish(f"diag/{event.get('subsystem', 'core')}", event,
                                       station=station, qos=1)
        except Exception:  # noqa: BLE001 — a debug mirror must never affect the app
            pass


class Diagnostics:
    def __init__(
        self,
        station: str,
        source_version: str,
        sinks: list[Sink] | None = None,
        default_level: str = "debug",
    ) -> None:
        self.station = station
        self.source_version = source_version
        self.sinks: list[Sink] = sinks if sinks is not None else [stdout_sink]
        self._seq = 0
        self._started = False
        # Per-subsystem minimum level. Default "debug" = emit everything (today's
        # behavior); a deployment can raise the floor and then a live control
        # (REMOTE_DEBUG.md §3.5) can bump one subsystem back down to see more.
        self._default_min = _LEVEL_INDEX.get(default_level, 0)
        self._overrides: dict[str, int] = {}

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def add_sink(self, sink: Sink) -> None:
        self.sinks.append(sink)

    # --- live per-subsystem level control (REMOTE_DEBUG.md §3.5) ------------

    def set_level(self, subsystem: str, level: str) -> None:
        if level not in _LEVEL_INDEX:
            raise ValueError(f"unknown level {level!r}; one of {LEVELS}")
        self._overrides[subsystem] = _LEVEL_INDEX[level]

    def get_levels(self) -> dict[str, str]:
        floor = LEVELS[self._default_min]
        return {"default": floor, "overrides": {s: LEVELS[i] for s, i in self._overrides.items()}}

    def _passes(self, level: str, subsystem: str) -> bool:
        floor = self._overrides.get(subsystem, self._default_min)
        return _LEVEL_INDEX.get(level, 0) >= floor

    # --- emit --------------------------------------------------------------

    def _emit(
        self,
        level: str,
        subsystem: str,
        message: str,
        context: dict[str, Any],
        exception: dict | None = None,
    ) -> dict:
        # Check the level FIRST and return before building the event / touching sinks
        # when it is filtered out (REMOTE_DEBUG.md §3.5 / §7.1 — no wasted allocation).
        if not self._passes(level, subsystem):
            return {}
        self._seq += 1
        event = {
            "seq": self._seq,
            "ts": time.time(),
            "level": level,
            "subsystem": subsystem,
            "message": message,
            "context": context or {},
            "exception": exception,
            "station": self.station,
            "source_version": self.source_version,
        }
        for sink in self.sinks:
            try:
                sink(event)
            except Exception:  # noqa: BLE001 — a broken sink must never kill the emitter
                traceback.print_exc(file=sys.stderr)
        return event

    def debug(self, subsystem: str, message: str, **context: Any) -> dict:
        return self._emit("debug", subsystem, message, context)

    def info(self, subsystem: str, message: str, **context: Any) -> dict:
        return self._emit("info", subsystem, message, context)

    def warning(self, subsystem: str, message: str, **context: Any) -> dict:
        return self._emit("warning", subsystem, message, context)

    def error(self, subsystem: str, message: str, **context: Any) -> dict:
        return self._emit("error", subsystem, message, context)

    def critical(self, subsystem: str, message: str, **context: Any) -> dict:
        return self._emit("critical", subsystem, message, context)

    def exception(
        self,
        subsystem: str,
        message: str,
        exc: BaseException | None = None,
        **context: Any,
    ) -> dict:
        exc = exc or sys.exc_info()[1]
        info = None
        if exc is not None:
            info = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            }
        return self._emit("error", subsystem, message, context, exception=info)

    @contextmanager
    def timed(self, subsystem: str, message: str, **context: Any):
        """Time a span; emit on success with elapsed_ms, or as an exception on failure."""
        t0 = time.perf_counter()
        try:
            yield
        except Exception as exc:
            context["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            self.exception(subsystem, f"{message} failed", exc, **context)
            raise
        else:
            context["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            self.info(subsystem, message, **context)

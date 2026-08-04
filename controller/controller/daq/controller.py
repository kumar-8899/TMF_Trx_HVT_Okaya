"""Per-station DAQ vertical (PYTHON_CONTROLLER.md §9.5): serves the `daq.*` ops and owns
the AI/DI stream publishers. DO writes are NOT here — they bind as ordinary signals in the
variable map (§9.5), reached through variable.write."""

from __future__ import annotations

from controller.daq.source import make_source
from controller.daq.stream import StreamPublisher


class DaqController:
    def __init__(self, station: str, publish, *, config: dict | None = None, simulation: bool = True):
        cfg = config or {}
        source = make_source(bool(cfg.get("simulated", simulation)), cfg.get("params"))
        rate = float(cfg.get("rate_hz", 100.0))
        batch = int(cfg.get("batch", 10))
        self.station = station
        self._pub = {
            "ai": StreamPublisher("ai", publish, source, rate_hz=rate, batch=batch,
                                  default_channels=cfg.get("ai_channels")),
            "di": StreamPublisher("di", publish, source, rate_hz=rate, batch=batch,
                                  default_channels=cfg.get("di_channels")),
        }

    def stream_start(self, signal: str, args: dict | None) -> dict:
        return self._pub[signal].start(args or {})

    def stream_stop(self, signal: str) -> dict:
        return self._pub[signal].stop()

    def read(self, signal: str, args: dict | None) -> dict:
        return {"result": self._pub[signal].read((args or {}).get("channels"))}

    def is_running(self, signal: str) -> bool:
        return self._pub[signal].running

    def stop_all(self) -> None:
        for p in self._pub.values():
            p.stop()


def register_daq_ops(client, daq: DaqController) -> None:
    for sig in ("ai", "di"):
        client.serve(f"daq.{sig}.stream.start", (lambda a, s=sig: daq.stream_start(s, a)))
        client.serve(f"daq.{sig}.stream.stop", (lambda a, s=sig: daq.stream_stop(s)))
        client.serve(f"daq.{sig}.read", (lambda a, s=sig: daq.read(s, a)))

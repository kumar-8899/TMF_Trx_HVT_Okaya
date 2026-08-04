"""Stream publisher — batched AI/DI frames at QoS 0 (PYTHON_CONTROLLER.md §9.5).

One background thread per (station, signal). A frame carries `batch` samples per channel
in a single MQTT message; batch + rate are config, not code — the throughput scaling axis.
QoS 0 + latest-wins: stream loss under load is expected and correct (LABVIEW_BRIDGE §6);
these are never bridged to the central broker."""

from __future__ import annotations

import threading
import time

from controller.daq.source import _channel_list


class StreamPublisher:
    def __init__(self, signal: str, publish, source, *, rate_hz: float = 100.0,
                 batch: int = 10, default_channels=None):
        self.signal = signal
        self._publish = publish            # publish(sub_topic, payload, qos)
        self._source = source
        self._rate = float(rate_hz)
        self._batch = max(1, int(batch))
        self._default = default_channels
        self._channels: list[str] = []
        self._running = False
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self, args: dict) -> dict:
        if self._running:
            return {"started": True, "already": True}
        self._channels = _channel_list(self.signal, args.get("channels", self._default))
        if args.get("rate"):
            self._rate = float(args["rate"])
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"daq-{self.signal}", daemon=True)
        self._thread.start()
        return {"started": True, "signal": self.signal, "rate": self._rate,
                "batch": self._batch, "channels": self._channels}

    def stop(self) -> dict:
        self._running = False
        return {"stopped": True, "signal": self.signal}

    def read(self, channels=None) -> dict:
        chans = _channel_list(self.signal, channels if channels is not None else self._default)
        return {"ts": time.time(), "signal": self.signal, "channels": self._source.read(self.signal, chans)}

    def _frame(self) -> dict:
        cols: dict[str, list] = {c: [] for c in self._channels}
        for _ in range(self._batch):
            sample = self._source.read(self.signal, self._channels)
            for c in self._channels:
                cols[c].append(sample[c])
        return {"ts": time.time(), "signal": self.signal, "rate": self._rate,
                "batch": self._batch, "channels": cols}

    def _loop(self) -> None:
        interval = self._batch / self._rate if self._rate > 0 else 0.1
        while self._running:
            try:
                self._publish(f"stream/{self.signal}", self._frame(), 0)   # QoS 0
            except Exception:  # noqa: BLE001 — a stream hiccup must not kill the thread
                pass
            time.sleep(interval)

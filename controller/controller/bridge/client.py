"""One MQTT client per station (PYTHON_CONTROLLER.md §2.1, §3.4).

Each station needs its own connection so it carries its own Last Will — one station's
controller dying flips only that station's retained `status`. The connect sequence is
LABVIEW_BRIDGE.md §8:

    set LWT -> connect -> publish status=online (retained)
            -> subscribe cmd/+ -> start periodic status republish

Served ops register via `serve(op, handler, blocking=?)`; `handler(args) -> dict` and its
return is replied to the request's `reply_to`. C1 serves only `hello.echo`; the sequencer
ops arrive in C3.

**Dispatch (why fast ops stay fast):** paho reads and dispatches every message on ONE
network thread. A handler that blocks it — e.g. an instrument read that waits the full
device timeout — freezes ALL command handling until it returns: no other instrument's read,
no `hello.echo`, no keepalive. So a handler registered `blocking=True` (the hardware ops:
`variable.*`, `instrument.test`/`call`) runs on a small **daemon dispatch pool** instead,
and `_on_message` returns immediately and keeps pumping. Fast, non-hardware ops (`hello.echo`,
`instrument.status`, run/safety/maintenance) run INLINE, so they are never queued behind a
slow instrument. Per-instrument serialization is unchanged — it comes from InstrumentBase's
per-instance `asyncio.Lock`, so distinct instruments run concurrently while same-instrument
calls serialize on that lock (PYTHON_CONTROLLER.md §3.4).
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Callable

import paho.mqtt.client as mqtt

from controller.bridge.envelope import decode, op_from_topic, reply_payload, reply_topic

Handler = Callable[[dict], dict]

_STATUS_ONLINE = {"state": "online"}
_STATUS_OFFLINE = {"state": "offline"}


class _DispatchPool:
    """A tiny pool of DAEMON worker threads for off-network-thread command dispatch. Daemon so a
    hung handler can never block controller shutdown — the process exits and the OS reaps the
    stuck thread; the backend's job-object backstop (launcher._WinJob) then guarantees no orphan.
    Ordering is not preserved (replies carry their request `id`, so the app correlates by id)."""

    def __init__(self, size: int, name: str) -> None:
        self._q: queue.Queue = queue.Queue()
        self._threads = [threading.Thread(target=self._worker, name=f"{name}-{i}", daemon=True)
                         for i in range(max(1, size))]
        for t in self._threads:
            t.start()

    def submit(self, fn: Callable[[], None]) -> None:
        self._q.put(fn)

    def _worker(self) -> None:
        while True:
            fn = self._q.get()
            if fn is None:
                return
            try:
                fn()
            except Exception:  # noqa: BLE001 — a job builds its own structured reply; never crash a worker
                pass

    def stop(self) -> None:
        for _ in self._threads:
            self._q.put(None)   # best-effort poison; workers are daemon, so exit never blocks


class StationClient:
    def __init__(self, station: str, *, host: str = "127.0.0.1", port: int = 1883,
                 keepalive: int = 30, status_period_s: float = 15.0,
                 dispatch_workers: int = 8,
                 on_log: Callable[[str, str], None] | None = None) -> None:
        self.station = station
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._status_period_s = status_period_s
        self._on_log = on_log
        self._served: dict[str, tuple[Handler, bool]] = {}   # op -> (handler, blocking)
        # Off-network-thread dispatch for blocking (hardware) handlers — see module docstring.
        self._pool = _DispatchPool(dispatch_workers, f"tmf-dispatch-{station}")

        self._status_topic = f"tmf/{station}/status"
        self._cmd_filter = f"tmf/{station}/cmd/+"
        self._client_id = f"tmf-ctl-{station}-{uuid.uuid4().hex[:8]}"
        self._resp_topic = f"tmf/{station}/query/resp/{self._client_id}"
        self._pending: dict[str, dict | None] = {}     # rid -> reply (controller->app queries)
        self._pending_ev: dict[str, threading.Event] = {}

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self._client_id,
                                   protocol=mqtt.MQTTv311)
        self._client.on_connect = self._on_connect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_message = self._on_message
        self._client.will_set(self._status_topic, json.dumps(_STATUS_OFFLINE), qos=1, retain=True)

        self._status_timer: threading.Timer | None = None
        self._connected = threading.Event()

    # --- registration ------------------------------------------------------

    def serve(self, op: str, handler: Handler, *, blocking: bool = False) -> None:
        """Register a cmd-op handler. `blocking=True` (hardware ops that wait on device I/O)
        runs it on the dispatch pool so it never freezes the network thread; the default
        (fast, non-hardware ops) runs inline for minimum latency (module docstring)."""
        self._served[op] = (handler, blocking)

    def publish(self, sub_topic: str, payload: dict, *, qos: int = 1, retain: bool = False) -> None:
        """Publish to `tmf/{station}/{sub_topic}` (e.g. retained `value/<name>`)."""
        self._client.publish(f"tmf/{self.station}/{sub_topic}", json.dumps(payload),
                             qos=qos, retain=retain)

    def request(self, op: str, args: dict, *, timeout: float = 5.0) -> dict:
        """Issue a query/{op} to the app and block for the reply (e.g. recipe.fetch at
        run start, §3.2). Runs on a station thread, not the MQTT loop, so blocking is
        fine. Raises TimeoutError on no reply."""
        rid = uuid.uuid4().hex
        ev = threading.Event()
        self._pending_ev[rid] = ev
        self._client.publish(f"tmf/{self.station}/query/{op}",
                             json.dumps({"id": rid, "op": op, "args": args,
                                         "reply_to": self._resp_topic}), qos=1)
        if not ev.wait(timeout):
            self._pending_ev.pop(rid, None)
            raise TimeoutError(f"no reply for query '{op}' within {timeout}s")
        return self._pending.pop(rid, None) or {}

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._client.connect(self._host, self._port, keepalive=self._keepalive)
        self._client.loop_start()

    def wait_connected(self, timeout: float = 5.0) -> bool:
        return self._connected.wait(timeout)

    def stop(self) -> None:
        if self._status_timer is not None:
            self._status_timer.cancel()
        self._pool.stop()   # poison the dispatch workers (daemon — a hung one never blocks exit)
        try:
            # graceful offline (retained) so subscribers see it without waiting for the LWT
            self._client.publish(self._status_topic, json.dumps(_STATUS_OFFLINE), qos=1, retain=True)
            time.sleep(0.05)
        except Exception:  # noqa: BLE001
            pass
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    # --- paho callbacks ----------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            self._log("warning", f"connect failed: {reason_code}")
            return
        client.publish(self._status_topic, json.dumps(_STATUS_ONLINE), qos=1, retain=True)
        client.subscribe(self._cmd_filter, qos=1)   # _connected is set on SUBACK, not here
        client.subscribe(self._resp_topic, qos=1)   # replies to our controller->app queries

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties=None) -> None:
        # Only mark connected once cmd/+ is actually subscribed — otherwise a caller that
        # publishes immediately after wait_connected() can race ahead of the SUBACK and
        # the broker drops the command.
        if not self._connected.is_set():
            self._connected.set()
            self._schedule_status()
            self._log("info", f"{self.station} online, serving {sorted(self._served)}")

    def _on_message(self, client, userdata, message) -> None:
        if message.topic == self._resp_topic:      # reply to a controller->app query
            reply = decode(message.payload) or {}
            rid = reply.get("id")
            ev = self._pending_ev.pop(rid, None) if rid else None
            if ev is not None:
                self._pending[rid] = reply
                ev.set()
            return
        op = op_from_topic(message.topic)
        if op is None or op == "resp":
            return
        request = decode(message.payload) or {}
        entry = self._served.get(op)
        if entry is None:
            self._publish_reply(request, reply_payload(request, error={
                "code": "unknown_op", "message": f"no handler for '{op}'"}))
            return
        handler, blocking = entry
        if blocking:
            # Hand off to the dispatch pool so a slow device I/O never freezes the network thread
            # (and every other op behind it). _on_message returns immediately and keeps pumping.
            self._pool.submit(lambda: self._invoke_and_reply(handler, request))
        else:
            self._invoke_and_reply(handler, request)   # fast, non-hardware op: inline, lowest latency

    def _invoke_and_reply(self, handler: Handler, request: dict) -> None:
        """Run a served handler and publish its reply. Any exception collapses to the structured
        `handler_failed` error (unchanged contract) — a handler that itself returns an `ok:false`
        envelope, e.g. instrument.call, keeps its specific error code by not raising."""
        try:
            reply = reply_payload(request, result=handler(request.get("args") or {}))
        except Exception as exc:  # noqa: BLE001 — structured error, never crash the thread/worker
            reply = reply_payload(request, error={"code": "handler_failed", "message": str(exc)})
        self._publish_reply(request, reply)

    def _publish_reply(self, request: dict, reply: dict) -> None:
        dest = reply_topic(request)   # the reply goes to the request's reply_to
        if dest:
            self._client.publish(dest, json.dumps(reply), qos=1)

    # --- periodic status ---------------------------------------------------

    def _schedule_status(self) -> None:
        self._status_timer = threading.Timer(self._status_period_s, self._republish_status)
        self._status_timer.daemon = True
        self._status_timer.start()

    def _republish_status(self) -> None:
        try:
            self._client.publish(self._status_topic, json.dumps(_STATUS_ONLINE), qos=1, retain=True)
        finally:
            self._schedule_status()

    def _log(self, level: str, message: str) -> None:
        if self._on_log is not None:
            self._on_log(level, message)

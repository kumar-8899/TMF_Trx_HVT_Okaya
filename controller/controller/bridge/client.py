"""One MQTT client per station (PYTHON_CONTROLLER.md §2.1, §3.4).

Each station needs its own connection so it carries its own Last Will — one station's
controller dying flips only that station's retained `status`. The connect sequence is
LABVIEW_BRIDGE.md §8:

    set LWT -> connect -> publish status=online (retained)
            -> subscribe cmd/+ -> start periodic status republish

Served ops register via `serve(op, handler)`; `handler(args) -> dict` runs on paho's
network thread and its return is replied to the request's `reply_to`. C1 serves only
`hello.echo`; the sequencer ops arrive in C3.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable

import paho.mqtt.client as mqtt

from controller.bridge.envelope import decode, op_from_topic, reply_payload, reply_topic

Handler = Callable[[dict], dict]

_STATUS_ONLINE = {"state": "online"}
_STATUS_OFFLINE = {"state": "offline"}


class StationClient:
    def __init__(self, station: str, *, host: str = "127.0.0.1", port: int = 1883,
                 keepalive: int = 30, status_period_s: float = 15.0,
                 on_log: Callable[[str, str], None] | None = None) -> None:
        self.station = station
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._status_period_s = status_period_s
        self._on_log = on_log
        self._served: dict[str, Handler] = {}

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

    def serve(self, op: str, handler: Handler) -> None:
        self._served[op] = handler

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
        handler = self._served.get(op)
        if handler is None:
            reply = reply_payload(request, error={"code": "unknown_op",
                                                  "message": f"no handler for '{op}'"})
        else:
            try:
                reply = reply_payload(request, result=handler(request.get("args") or {}))
            except Exception as exc:  # noqa: BLE001 — structured error, never crash the thread
                reply = reply_payload(request, error={"code": "handler_failed",
                                                      "message": str(exc)})
        dest = reply_topic(request)
        if dest:
            client.publish(dest, json.dumps(reply), qos=1)

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

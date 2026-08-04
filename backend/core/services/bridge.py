"""MQTT bridge client — the Python side of LABVIEW_BRIDGE.md (CORE.md §1, §9).

One MQTT client exposing publish / request / subscribe to the rest of the
platform. Topics are scoped `tmf/{station}/…` (BRIDGE §3); callers pass the
sub-topic (e.g. "value/vbus_main", "cmd" via request) and this prefixes it.

Request/reply is 3.1.1-safe: the command payload carries `reply_to` + `id`, so a
3.1.1 responder (LabVIEW) needs no MQTT-5 features (BRIDGE §5). Python is a V5
client and also sets response-topic/correlation as an optional optimization. Link
liveness comes from the retained `status` topic: ready only when status=online
(BRIDGE §7, CORE.md §5).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiomqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

Handler = Callable[[str, dict | None], Awaitable[None] | None]


class BridgeError(Exception):
    """Bridge not connected, or a publish/request could not be issued."""


class BridgeTimeout(BridgeError):
    """A request got no reply within its timeout. Python maps this to HTTP 502."""


def topic_matches(filter_: str, topic: str) -> bool:
    """MQTT topic-filter match supporting + and # (single/multi-level wildcards)."""
    f, t = filter_.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t):
            return False
        if part != "+" and part != t[i]:
            return False
    return len(f) == len(t)


@dataclass
class _Sub:
    sub_topic: str
    full_topic: str
    handler: Handler


class BridgeClient:
    def __init__(
        self,
        station: str,
        *,
        host: str = "127.0.0.1",
        port: int = 1883,
        client_id: str | None = None,
        diag=None,
        request_timeout: float = 5.0,
        reconnect_delay: float = 1.0,
    ) -> None:
        self.station = station
        self._host = host
        self._port = port
        self._client_id = client_id or f"tmf-py-{uuid.uuid4().hex[:8]}"
        self._diag = diag
        self._request_timeout = request_timeout
        self._reconnect_delay = reconnect_delay

        self._resp_topic = f"tmf/{station}/cmd/resp/{self._client_id}"
        self._status_topic = f"tmf/{station}/status"

        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._stop = False
        self._connected = False
        self._link_online = False
        self._connected_event = asyncio.Event()
        self._pending: dict[str, asyncio.Future] = {}
        self._subs: list[_Sub] = []
        self._latest: dict[str, dict] = {}  # full_topic -> last payload (BRIDGE §6)
        self._served: dict[str, Handler] = {}  # full query topic -> handler (Py-served, BRIDGE §5)

    # --- topic helpers -----------------------------------------------------

    def _full(self, sub_topic: str) -> str:
        return f"tmf/{self.station}/{sub_topic}"

    def latest(self, sub_topic: str) -> dict | None:
        """Last payload seen on a subscribed topic (e.g. 'stream/ai',
        'value/vbus_main'). Snapshot-on-join for WS + REST (BRIDGE §6)."""
        return self._latest.get(self._full(sub_topic))

    # --- link state --------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Broker connection is up."""
        return self._connected

    @property
    def online(self) -> bool:
        """Broker up AND the LabVIEW link reports status=online (CORE.md §5)."""
        return self._connected and self._link_online

    # --- lifecycle ---------------------------------------------------------

    async def connect(self, wait_timeout: float = 5.0) -> bool:
        """Start the connection supervisor; wait briefly for the broker.

        Returns whether the broker connected in time. If not, the supervisor
        keeps retrying in the background and the app boots not-ready (HAL rule).
        """
        self._stop = False
        self._task = asyncio.create_task(self._run(), name="bridge-supervisor")
        try:
            await asyncio.wait_for(self._connected_event.wait(), wait_timeout)
            return True
        except asyncio.TimeoutError:
            self._log("warning", "broker not reachable yet; retrying in background")
            return False

    async def disconnect(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stop:
            try:
                async with aiomqtt.Client(
                    hostname=self._host,
                    port=self._port,
                    identifier=self._client_id,
                    protocol=aiomqtt.ProtocolVersion.V5,
                ) as client:
                    self._client = client
                    self._connected = True
                    await client.subscribe(self._resp_topic, qos=1)
                    await client.subscribe(self._status_topic, qos=1)
                    for sub in self._subs:
                        await client.subscribe(sub.full_topic, qos=1)
                    for query_topic in self._served:
                        await client.subscribe(query_topic, qos=1)
                    self._connected_event.set()
                    self._log("info", "bridge connected", host=self._host, port=self._port)
                    async for message in client.messages:
                        self._dispatch(message)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 — reconnect on any broker error
                self._log("warning", "bridge connection lost", error=str(exc))
            finally:
                self._connected = False
                self._link_online = False
                self._client = None
                self._connected_event.clear()
            if self._stop:
                break
            await asyncio.sleep(self._reconnect_delay)

    # --- inbound dispatch --------------------------------------------------

    def _dispatch(self, message) -> None:
        topic = message.topic.value
        try:
            payload = json.loads(message.payload) if message.payload else None
        except (json.JSONDecodeError, TypeError):
            payload = None

        if topic == self._resp_topic:
            self._resolve_reply(message, payload)
            return

        if topic == self._status_topic:
            state = (payload or {}).get("state")
            was = self._link_online
            self._link_online = state == "online"
            if was != self._link_online:
                self._log("info", "bridge link status", state=state)
            return

        if topic in self._served:
            asyncio.create_task(self._handle_query(self._served[topic], payload))
            return

        # Keep only the latest frame per topic (BRIDGE §6) for snapshot-on-join.
        if payload is not None:
            self._latest[topic] = payload

        for sub in self._subs:
            if topic_matches(sub.full_topic, topic):
                self._invoke(sub.handler, topic, payload)

    def _resolve_reply(self, message, payload: dict | None) -> None:
        rid = None
        props = getattr(message, "properties", None)
        corr = getattr(props, "CorrelationData", None) if props else None
        if corr:
            rid = corr.decode() if isinstance(corr, (bytes, bytearray)) else str(corr)
        elif payload:
            rid = payload.get("id")
        fut = self._pending.pop(rid, None) if rid else None
        if fut is not None and not fut.done():
            fut.set_result(payload)

    def _invoke(self, handler: Handler, topic: str, payload: dict | None) -> None:
        result = handler(topic, payload)
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)

    # --- outbound ----------------------------------------------------------

    async def publish(
        self, sub_topic: str, payload: dict, *, qos: int = 1, retain: bool = False
    ) -> None:
        if self._client is None:
            raise BridgeError("bridge not connected")
        await self._client.publish(
            self._full(sub_topic), json.dumps(payload), qos=qos, retain=retain
        )

    def subscribe(self, sub_topic: str, handler: Handler) -> None:
        """Register a handler for a LV→Py topic. (Re)subscribed on each connect."""
        sub = _Sub(sub_topic, self._full(sub_topic), handler)
        self._subs.append(sub)
        if self._client is not None:
            asyncio.create_task(self._client.subscribe(sub.full_topic, qos=1))

    def serve(self, op: str, handler) -> None:
        """Serve a LV→Py request on query/{op} (BRIDGE §5). handler(args) -> result
        (sync or async); the reply goes to the request's payload reply_to + id.
        Distinct topic class from cmd/+ (which LabVIEW serves)."""
        full = self._full(f"query/{op}")
        self._served[full] = handler
        if self._client is not None:
            asyncio.create_task(self._client.subscribe(full, qos=1))

    async def _handle_query(self, handler, payload: dict | None) -> None:
        payload = payload or {}
        rid = payload.get("id")
        reply_to = payload.get("reply_to")
        try:
            result = handler(payload.get("args", {}))
            if asyncio.iscoroutine(result):
                result = await result
            reply = {"id": rid, "ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001 — return a structured error, never crash
            reply = {"id": rid, "ok": False,
                     "error": {"code": "query_failed", "message": str(exc), "detail": ""}}
        if reply_to and self._client is not None:
            await self._client.publish(reply_to, json.dumps(reply), qos=1)

    async def request(self, op: str, args: dict, timeout: float | None = None) -> dict:
        """Issue cmd/{op} and await the reply (BRIDGE §5)."""
        if self._client is None:
            raise BridgeError("bridge not connected")
        rid = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[rid] = fut

        props = Properties(PacketTypes.PUBLISH)
        props.ResponseTopic = self._resp_topic
        props.CorrelationData = rid.encode()

        # reply_to + id travel in the payload so a 3.1.1 responder (LabVIEW) can
        # reply without MQTT-5 response-topic/correlation (BRIDGE §5). The V5
        # properties above stay as an optional optimization.
        await self._client.publish(
            self._full(f"cmd/{op}"),
            json.dumps({"id": rid, "op": op, "args": args, "reply_to": self._resp_topic}),
            qos=1,
            properties=props,
        )
        try:
            return await asyncio.wait_for(fut, timeout or self._request_timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(rid, None)
            raise BridgeTimeout(f"no reply for '{op}' within timeout") from exc

    async def query(self, op: str, args: dict, timeout: float | None = None) -> dict:
        """Issue a query/{op} to a Python-served handler and await the reply.
        Same envelope as request(); the counterpart of serve()."""
        if self._client is None:
            raise BridgeError("bridge not connected")
        rid = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._client.publish(
            self._full(f"query/{op}"),
            json.dumps({"id": rid, "op": op, "args": args, "reply_to": self._resp_topic}),
            qos=1,
        )
        try:
            return await asyncio.wait_for(fut, timeout or self._request_timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(rid, None)
            raise BridgeTimeout(f"no reply for '{op}' within timeout") from exc

    # --- internal ----------------------------------------------------------

    def _log(self, level: str, message: str, **context) -> None:
        if self._diag is not None:
            getattr(self._diag, level)("bridge", message, **context)


class MultiStationBridge:
    """N stations, N MQTT connections (MULTI_STATION.md §2). One `BridgeClient` per
    station — each carries its own LWT + retained `status` so one socket dropping flips
    only that station's link. `request`/`publish` take a **required** `station` keyword
    (never defaulted — a default silently addresses the wrong socket, a wrong-DUT-verdict
    bug). `subscribe`/`serve` fan out to every station. The cache + link liveness are
    per station because each `BridgeClient` holds its own."""

    def __init__(self, stations: list[str], *, host: str = "127.0.0.1", port: int = 1883,
                 diag=None, request_timeout: float = 5.0, reconnect_delay: float = 1.0) -> None:
        if not stations:
            raise BridgeError("MultiStationBridge needs at least one station")
        self.stations = list(stations)
        self._diag = diag
        self._conns: dict[str, BridgeClient] = {
            st: BridgeClient(st, host=host, port=port, diag=diag,
                             request_timeout=request_timeout, reconnect_delay=reconnect_delay)
            for st in self.stations
        }

    def _conn(self, station: str) -> BridgeClient:
        conn = self._conns.get(station)
        if conn is None:
            raise BridgeError(f"unknown station '{station}' (have {self.stations})")
        return conn

    # --- lifecycle (all stations) -----------------------------------------

    async def connect(self, wait_timeout: float = 5.0) -> bool:
        results = await asyncio.gather(*(c.connect(wait_timeout) for c in self._conns.values()),
                                       return_exceptions=True)
        return any(r is True for r in results)

    async def disconnect(self) -> None:
        await asyncio.gather(*(c.disconnect() for c in self._conns.values()),
                             return_exceptions=True)

    # --- link state -------------------------------------------------------

    def link_status(self, station: str) -> str:
        return "online" if self._conn(station).online else "offline"

    @property
    def any_link_online(self) -> bool:
        return any(c.online for c in self._conns.values())

    @property
    def online(self) -> bool:
        """Back-compat: any station's link is up. Per-station callers use link_status()."""
        return self.any_link_online

    @property
    def connected(self) -> bool:
        return any(c.connected for c in self._conns.values())

    def link_map(self) -> dict[str, str]:
        return {st: self.link_status(st) for st in self.stations}

    # --- scoped I/O (station required) ------------------------------------

    async def request(self, op: str, args: dict, *, station: str, timeout: float | None = None) -> dict:
        return await self._conn(station).request(op, args, timeout)

    async def publish(self, sub_topic: str, payload: dict, *, station: str,
                      qos: int = 1, retain: bool = False) -> None:
        await self._conn(station).publish(sub_topic, payload, qos=qos, retain=retain)

    async def query(self, op: str, args: dict, *, station: str, timeout: float | None = None) -> dict:
        return await self._conn(station).query(op, args, timeout)

    def latest(self, sub_topic: str, station: str | None = None) -> dict | None:
        return self._conn(station or self.stations[0]).latest(sub_topic)

    # --- fan-out registration (all stations) ------------------------------

    def subscribe(self, sub_topic: str, handler: Handler) -> None:
        for c in self._conns.values():
            c.subscribe(sub_topic, handler)

    def serve(self, op: str, handler) -> None:
        """Serve a query op on every station. If the handler accepts a second argument
        it is called `handler(args, station)` so it can resolve against the calling
        socket; a one-arg handler is called `handler(args)` unchanged."""
        import inspect
        try:
            wants_station = len(inspect.signature(handler).parameters) >= 2
        except (TypeError, ValueError):
            wants_station = False
        for st, c in self._conns.items():
            c.serve(op, (lambda a, _st=st: handler(a, _st)) if wants_station else handler)

"""C3 live acceptance (PYTHON_CONTROLLER.md §16 C3): a real recipe runs end to end
over the broker. A probe plays the app — answers recipe.fetch, fires run.start, and
collects the event stream. Skipped when no broker."""

import json
import socket
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

import controller.step_types  # noqa: F401 — register the 8 core types
from controller.bridge.client import StationClient
from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import StationVariables
from controller.loop import AsyncLoopThread
from controller.runstate import RunEngine
from controller.serve import register_core_ops, register_run_ops, register_station_ops
from tester import _fakelib

HOST, PORT = "127.0.0.1", 1883


def _broker_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _broker_up(), reason="no MQTT broker on 127.0.0.1:1883")

_RECIPE = {"recipe_id": "demo", "steps": [
    {"type": "set_output", "id": "src", "params": {"signal": "dc", "value": 5}},
    {"type": "measure_and_compare", "id": "chk", "params": {"signal": "vbus", "min": 4, "max": 6}},
]}


class _App:
    """Stands in for the framework app: serves recipe.fetch, fires run.start, tails events."""

    def __init__(self, station):
        self.station = station
        self.events: list[tuple[str, dict]] = []
        self.replies: dict[str, dict] = {}
        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"app-{uuid.uuid4().hex[:6]}", protocol=mqtt.MQTTv311)
        self._c.on_message = self._on_message
        self._c.connect(HOST, PORT, 30)
        self._c.subscribe(f"tmf/{station}/#", qos=1)
        self._c.loop_start()

    def _on_message(self, c, u, m):
        try:
            p = json.loads(m.payload)
        except Exception:  # noqa: BLE001
            return
        if m.topic.endswith("/query/recipe.fetch"):                    # controller -> app
            c.publish(p["reply_to"], json.dumps({"id": p.get("id"), "ok": True, "result": _RECIPE}), qos=1)
        elif "/cmd/resp/app" in m.topic:                              # our run.start reply
            self.replies[p.get("id")] = p
        elif "/event/" in m.topic:
            self.events.append((p.get("type"), p.get("payload", {})))

    def run_start(self, timeout=5.0) -> dict:
        rid = uuid.uuid4().hex
        run_id = uuid.uuid4().hex
        self._c.publish(f"tmf/{self.station}/cmd/run.start",
                        json.dumps({"id": rid, "op": "run.start",
                                    "args": {"recipe_id": "demo", "run_id": run_id},
                                    "reply_to": f"tmf/{self.station}/cmd/resp/app"}), qos=1)
        end = time.time() + timeout
        while time.time() < end and rid not in self.replies:
            time.sleep(0.02)
        return self.replies.get(rid, {})

    def wait_event(self, etype, timeout=6.0) -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            for t, p in self.events:
                if t == etype:
                    return p
            time.sleep(0.02)
        return None

    def close(self):
        self._c.loop_stop()
        self._c.disconnect()


def test_c3_recipe_runs_end_to_end():
    lib = _fakelib.ensure_registered()
    station = f"c3_{uuid.uuid4().hex[:6]}"
    loop = AsyncLoopThread()
    loop.start()
    registry = InstrumentRegistry(loop)
    registry.build([{"id": "psu1", "library": lib, "simulated": True, "params": {"resource": "Z"}}])
    loop.run(registry.connect_all())
    vmap = {"signals": {
        "vbus": {"instance": "psu1", "read": "measure_voltage", "units": "V"},   # sim -> 5.0
        "dc": {"instance": "psu1", "write": "set_voltage", "units": "V"},
    }, "actions": {}}
    variables = StationVariables(station, vmap, registry, loop)

    app = _App(station)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    register_station_ops(client, variables, registry, loop)
    engine = RunEngine(station, variables=variables, emit=_emit(client),
                       recipe_fetch=_fetch(client), safe_state=lambda: loop.run(registry.safe_state_all()),
                       diag=lambda *a, **k: None)
    register_run_ops(client, engine)
    try:
        client.start()
        assert client.wait_connected(5.0)

        reply = app.run_start()
        assert reply.get("accepted") is True and reply.get("run_id")

        finished = app.wait_event("run-finished")
        assert finished is not None and finished["result"] == "PASS"
        types = [t for t, _ in app.events]
        assert types[0] == "run-started"
        assert "step-started" in types and "step-completed" in types and "test-result" in types
        # exactly one terminal
        assert sum(1 for t in types if t in ("run-finished", "run-aborted")) == 1
        chk = [p for t, p in app.events if t == "test-result" and p.get("step_id") == "chk"]
        assert chk and chk[0]["result"] == "PASS" and chk[0]["value"] == 5.0
    finally:
        client.stop()
        loop.run(registry.disconnect_all())
        loop.stop()
        app.close()


def _emit(client):
    def emit(etype, payload):
        client.publish(f"event/{etype}", {"type": etype, "ts": time.time(),
                                          "trace": f"run:{payload.get('run_id')}", "payload": payload})
    return emit


def _fetch(client):
    def fetch(recipe_id, version):
        r = client.request("recipe.fetch", {"recipe_id": recipe_id, "version": version})
        if not r.get("ok"):
            raise RuntimeError("recipe.fetch failed")
        return r.get("result") or {}
    return fetch

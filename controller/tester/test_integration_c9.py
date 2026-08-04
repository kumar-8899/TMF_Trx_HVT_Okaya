"""C9 live: an app-authored step type calls ctx.invoke on a 'multiplexer' action; the recipe
runs end to end over the broker and the route lands on the (simulated) device — proving
actions execute with NO instance id in the recipe or handler. Skipped when no broker."""

import json
import socket
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

import controller.step_types  # noqa: F401 — the 8 core types
from controller.bridge.client import StationClient
from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import StationVariables, check_action_capabilities
from controller.loop import AsyncLoopThread
from controller.registry import STEP_REGISTRY, register_step_type
from controller.results import INFO, Measurement, StepResult
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


# An app step type (would live in an app package, C10) that drives a non-scalar action.
if "route_and_measure" not in STEP_REGISTRY:
    @register_step_type(type_id="route_and_measure", display_name="Route & measure",
                        required_actions=("signal_mux",))
    class RouteAndMeasure:
        @staticmethod
        def bindings(params):
            return {"signals": [params["signal"]], "actions": ["signal_mux"]}

        def execute(self, params, ctx) -> StepResult:
            ctx.invoke("signal_mux", "set_route", [params["channel"], params["bus"]])
            value = ctx.read(params["signal"])
            return StepResult(measurements=[
                Measurement("route", params["bus"], status=INFO),
                Measurement(params["signal"], value, "V")])


_RECIPE = {"recipe_id": "mux", "steps": [
    {"type": "route_and_measure", "id": "rm",
     "params": {"signal": "vbus", "channel": 3, "bus": "busA"}},
]}


class _App:
    def __init__(self, station):
        self.station = station
        self.events, self.replies = [], {}
        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"app-{uuid.uuid4().hex[:6]}", protocol=mqtt.MQTTv311)
        self._c.on_message = self._on
        self._c.connect(HOST, PORT, 30)
        self._c.subscribe(f"tmf/{station}/#", qos=1)
        self._c.loop_start()

    def _on(self, c, u, m):
        try:
            p = json.loads(m.payload)
        except Exception:  # noqa: BLE001
            return
        if m.topic.endswith("/query/recipe.fetch"):
            c.publish(p["reply_to"], json.dumps({"id": p.get("id"), "ok": True, "result": _RECIPE}), qos=1)
        elif "/cmd/resp/app" in m.topic:
            self.replies[p.get("id")] = p
        elif "/event/" in m.topic:
            self.events.append((p.get("type"), p.get("payload", {})))

    def run_start(self, timeout=5.0):
        rid = uuid.uuid4().hex
        self._c.publish(f"tmf/{self.station}/cmd/run.start",
                        json.dumps({"id": rid, "op": "run.start",
                                    "args": {"recipe_id": "mux", "run_id": uuid.uuid4().hex},
                                    "reply_to": f"tmf/{self.station}/cmd/resp/app"}), qos=1)
        end = time.time() + timeout
        while time.time() < end and rid not in self.replies:
            time.sleep(0.02)
        return self.replies.get(rid, {})

    def wait_event(self, etype, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            for t, p in self.events:
                if t == etype:
                    return p
            time.sleep(0.02)
        return None

    def close(self):
        self._c.loop_stop(); self._c.disconnect()


def test_c9_action_runs_end_to_end():
    lib = _fakelib.ensure_registered()
    mux = _fakelib.ensure_mux_registered()
    station = f"c9_{uuid.uuid4().hex[:6]}"
    loop = AsyncLoopThread(); loop.start()
    reg = InstrumentRegistry(loop)
    reg.build([
        {"id": "psu1", "library": lib, "simulated": True, "params": {"resource": station + "p"}},
        {"id": "mux1", "library": mux, "simulated": True, "params": {"resource": station + "m"}},
    ])
    loop.run(reg.connect_all())
    vmap = {"signals": {"vbus": {"instance": "psu1", "read": "measure_voltage", "units": "V"}},
            "actions": {"signal_mux": {"instance": "mux1", "capability": "multiplexer"}}}
    assert check_action_capabilities({station: vmap}, reg) == []     # §4.1 verified at load

    variables = StationVariables(station, vmap, reg, loop)
    app = _App(station)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    register_station_ops(client, variables, reg, loop)
    engine = RunEngine(station, variables=variables,
                       emit=lambda t, p: client.publish(f"event/{t}", {"type": t, "ts": time.time(),
                                                                       "trace": f"run:{p.get('run_id')}", "payload": p}),
                       recipe_fetch=_fetch(client),
                       safe_state=lambda: loop.run(reg.safe_state_all()), diag=lambda *a, **k: None)
    register_run_ops(client, engine)
    try:
        client.start()
        assert client.wait_connected(5.0)
        assert app.run_start().get("accepted") is True
        fin = app.wait_event("run-finished")
        assert fin and fin["result"] == "PASS"
        assert reg.get("mux1").routes == {3: "busA"}             # the action reached the device
    finally:
        client.stop()
        loop.run(reg.disconnect_all())
        loop.stop()
        app.close()


def _fetch(client):
    def fetch(recipe_id, version):
        r = client.request("recipe.fetch", {"recipe_id": recipe_id, "version": version})
        if not r.get("ok"):
            raise RuntimeError("recipe.fetch failed")
        return r.get("result") or {}
    return fetch

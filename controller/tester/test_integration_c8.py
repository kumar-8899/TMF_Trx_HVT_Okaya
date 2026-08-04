"""C8 live: dry run over the broker (§12.2) and a full recipe run with NO hardware (§12.1
simulation). A probe plays the app — serves recipe.fetch, fires run.start, tails events.
Skipped when no broker."""

import json
import socket
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

import controller.step_types  # noqa: F401
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

# 'iout' is intentionally NOT in the station map — dry run must catch it.
_RECIPE = {"recipe_id": "demo", "steps": [
    {"type": "set_output", "id": "src", "params": {"signal": "dc", "value": 5}},
    {"type": "measure_and_compare", "id": "chk", "params": {"signal": "vbus", "min": 4, "max": 6}},
    {"type": "measure_and_compare", "id": "bad", "params": {"signal": "iout", "min": 0, "max": 1}},
]}
_GOOD = {"recipe_id": "good", "steps": _RECIPE["steps"][:2]}


class _App:
    def __init__(self, station, recipes):
        self.station = station
        self.recipes = recipes
        self.events = []
        self.replies = {}
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
            rid = (p.get("args") or {}).get("recipe_id")
            c.publish(p["reply_to"], json.dumps(
                {"id": p.get("id"), "ok": True, "result": self.recipes.get(rid, _RECIPE)}), qos=1)
        elif "/cmd/resp/app" in m.topic:
            self.replies[p.get("id")] = p
        elif "/event/" in m.topic:
            self.events.append((p.get("type"), p.get("payload", {})))

    def run_start(self, recipe_id, *, dry_run=False, timeout=5.0):
        rid = uuid.uuid4().hex
        args = {"recipe_id": recipe_id, "run_id": uuid.uuid4().hex}
        if dry_run:
            args["dry_run"] = True
        self._c.publish(f"tmf/{self.station}/cmd/run.start",
                        json.dumps({"id": rid, "op": "run.start", "args": args,
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
        self._c.loop_stop()
        self._c.disconnect()


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


def _bring_up(station):
    lib = _fakelib.ensure_registered()
    loop = AsyncLoopThread(); loop.start()
    reg = InstrumentRegistry(loop)
    # simulation=True at the registry: EVERY instrument simulated, no card present (§12.1)
    reg.build([{"id": "psu1", "library": lib, "params": {"resource": station}}], simulation=True)
    loop.run(reg.connect_all())
    vmap = {"signals": {"vbus": {"instance": "psu1", "read": "measure_voltage", "units": "V"},
                        "dc": {"instance": "psu1", "write": "set_voltage", "units": "V"}},
            "actions": {}}
    variables = StationVariables(station, vmap, reg, loop)
    client = StationClient(station, host=HOST, port=PORT, status_period_s=60)
    register_core_ops(client)
    register_station_ops(client, variables, reg, loop)
    engine = RunEngine(station, variables=variables, emit=_emit(client), recipe_fetch=_fetch(client),
                       safe_state=lambda: loop.run(reg.safe_state_all()), diag=lambda *a, **k: None)
    register_run_ops(client, engine)
    return loop, reg, client


def test_c8_dry_run_and_cardless_run():
    station = f"c8_{uuid.uuid4().hex[:6]}"
    app = _App(station, {"demo": _RECIPE, "good": _GOOD})
    loop, reg, client = _bring_up(station)
    try:
        client.start()
        assert client.wait_connected(5.0)
        assert reg.get("psu1").simulated is True                 # §12.1 — simulated, no hardware

        # dry run of the recipe with a missing signal -> DRY_RUN_FAIL, error names it
        assert app.run_start("demo", dry_run=True).get("accepted") is True
        fin = app.wait_event("run-finished")
        assert fin["result"] == "DRY_RUN_FAIL"
        assert any("iout" in e for e in fin["errors"])
        assert "step-started" not in [t for t, _ in app.events]  # no steps executed

        # a full run of the clean recipe, cardless -> PASS
        app.events.clear()
        assert app.run_start("good").get("accepted") is True
        fin = app.wait_event("run-finished")
        assert fin["result"] == "PASS"
        chk = [p for t, p in app.events if t == "test-result" and p.get("step_id") == "chk"]
        assert chk and chk[0]["result"] == "PASS" and chk[0]["value"] == 5.0
    finally:
        client.stop()
        loop.run(reg.disconnect_all())
        loop.stop()
        app.close()

"""cmd-op handlers (PYTHON_CONTROLLER.md §3.1).

C1: `hello.echo`. C2: `variable.read` / `variable.write` (controller-owned scalar signals,
by name, resolved against the station's map) and `instrument.test` (open + identity ->
pass/fail). Each variable read/write also republishes the retained `value/<name>` snapshot
(§3.3) so the app's last-value cache stays warm. Run/sequencer ops arrive in C3.

A handler returns the dict merged into the reply after `{id, ok}`; nesting a scalar read
under `result` matches the app's `variable.read` consumer, and returning an explicit `ok`
lets `instrument.test` report fail without raising."""

from __future__ import annotations

import time

from controller import registry as step_registry
from controller.bridge.client import StationClient
from controller.instruments.registry import InstrumentRegistry
from controller.instruments.variables import StationVariables


def hello_echo(args: dict) -> dict:
    """Echo args and stamp the controller's wall-clock ts — the app's latency +
    clock-skew probe (PYTHON_CONTROLLER.md §3.1)."""
    return {**(args or {}), "ts": time.time(), "controller": "python"}


def register_core_ops(client: StationClient) -> None:
    client.serve("hello.echo", hello_echo)


def register_station_ops(client: StationClient, variables: StationVariables,
                         registry: InstrumentRegistry, loop) -> None:
    """Instrument-facing ops for one station."""

    def variable_read(args: dict) -> dict:
        r = variables.read(args["name"])
        client.publish(f"value/{r['name']}", r, retain=True)   # warm the last-value cache
        return {"result": r}

    def variable_write(args: dict) -> dict:
        r = variables.write(args["name"], args["value"])
        client.publish(f"value/{r['name']}", {"name": r["name"], "value": r["written"]}, retain=True)
        return {"result": r}

    def variable_read_many(args: dict) -> dict:
        return {"result": {n: variables.read(n) for n in (args.get("names") or [])}}

    def instrument_test(args: dict) -> dict:
        iid = args.get("id") or args.get("instance")
        if not iid:
            return {"ok": False, "status": "error", "detail": "instrument.test needs 'id'"}
        inst = registry.get(iid)
        if inst is None:
            return {"ok": False, "status": "unavailable", "detail": f"no instance '{iid}'"}
        try:
            idn = loop.run(inst.invoke("identify"), timeout=8.0)
            ok = inst.state == "connected"
            return {"ok": ok, "status": "pass" if ok else "fail",
                    "identity": str(idn), "detail": f"state: {inst.state}"}
        except Exception as exc:  # noqa: BLE001 — an open failure is a fail verdict, not a crash
            return {"ok": False, "status": "fail", "detail": str(exc)}

    client.serve("variable.read", variable_read)
    client.serve("variable.write", variable_write)
    client.serve("variable.read_many", variable_read_many)
    client.serve("instrument.test", instrument_test)


def register_run_ops(client: StationClient, engine) -> None:
    """Run control + step-type introspection (PYTHON_CONTROLLER.md §3.1). engine.start
    accepts iff idle and returns {run_id, accepted}; it spawns the run thread and returns
    at once, so the MQTT loop is never blocked."""
    client.serve("run.start", lambda a: engine.start(a))
    client.serve("run.abort", lambda a: engine.abort())
    client.serve("sequencer.list_test_classes", lambda a: {"test_classes": step_registry.list_test_classes()})


def register_safety_ops(client: StationClient, safety) -> None:
    """Safety ops (PYTHON_CONTROLLER.md §10). `safety.trip` is one trip source — a manual
    E-stop over the bridge; it only enqueues, the reflex thread does the fan-out (independent
    of the bridge). `safety.clear` un-faults (maintenance-gated app-side, §10.4). The one
    SafetyController is shared across stations, so these are served on every station's client."""
    client.serve("safety.trip", lambda a: safety.trip((a or {}).get("monitor_id") or (a or {}).get("id")))
    client.serve("safety.clear", lambda a: safety.clear((a or {}).get("monitor_id") or (a or {}).get("id")))
    client.serve("safety.status", lambda a: safety.status())

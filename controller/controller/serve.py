"""cmd-op handlers (PYTHON_CONTROLLER.md §3.1).

C1: `hello.echo`. C2: `variable.read` / `variable.write` (controller-owned scalar signals,
by name, resolved against the station's map) and `instrument.test` (open + identity ->
pass/fail). Each variable read/write also republishes the retained `value/<name>` snapshot
(§3.3) so the app's last-value cache stays warm. Run/sequencer ops arrive in C3.

`instrument.call` / `instrument.status` (single-client-instrument race fix): when the app
runs a supervised Python controller, the backend's own instrument registry never opens a
direct connection to an owner=python instrument any more — it proxies every call and every
status read through THIS process's one live connection instead, via these two verbs. They
generalize `instrument.test`'s existing "resolve id -> call the instrument" pattern from
identify()-only to any method, and expose this registry's already-existing `status()`.

A handler returns the dict merged into the reply after `{id, ok}`; nesting a scalar read
under `result` matches the app's `variable.read` consumer, and returning an explicit `ok`
lets `instrument.test`/`instrument.call` report fail without raising (a handler exception
here would otherwise collapse to the generic `handler_failed` code and lose the specific
InstrumentError type the backend needs to reconstruct)."""

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

    def instrument_call(args: dict) -> dict:
        """Backend proxy seam: `{instance_id, method, args}` -> the same
        `registry.require(id).invoke(method, *args)` path `instrument.test`/StationVariables
        already use, generalized to any capability method. On failure, `code` carries the
        instrumentlib exception's own class name so the backend can reconstruct it
        (NotConnected/NotSupported/DeviceError/CommandTimeout/GarbageResponse/
        IdentityMismatch) rather than collapsing to a generic error."""
        iid = args.get("instance_id") or args.get("id") or args.get("instance")
        method = args.get("method")
        call_args = args.get("args") or []
        if not iid or not method:
            return {"ok": False, "error": {"code": "NotSupported",
                                           "message": "instrument.call needs 'instance_id' and 'method'",
                                           "detail": None}}
        inst = registry.get(iid)
        if inst is None:
            return {"ok": False, "error": {"code": "NotConnected",
                                           "message": f"no instance '{iid}' loaded",
                                           "detail": None}}
        try:
            result = loop.run(inst.invoke(method, *call_args), timeout=20.0)
            return {"ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001 — structured error, never raise out of a bridge handler
            return {"ok": False, "error": {"code": type(exc).__name__, "message": str(exc),
                                           "detail": getattr(exc, "detail", None)}}

    def instrument_status(args: dict) -> dict:
        """Backend proxy seam: live per-instance state, straight off this registry's
        existing `status()` — optionally filtered to `ids`. Never fails."""
        ids = args.get("ids")
        rows = registry.status()
        if ids:
            want = set(ids)
            rows = [r for r in rows if r.get("id") in want]
        return {"ok": True, "result": {"instances": rows}}

    # Hardware ops wait on device I/O — dispatch them OFF the network thread (blocking=True) so a
    # slow/hung instrument never freezes command handling for every other op. instrument.status is
    # a cached read (no I/O), so it stays inline and answers instantly even while a read is stuck.
    client.serve("variable.read", variable_read, blocking=True)
    client.serve("variable.write", variable_write, blocking=True)
    client.serve("variable.read_many", variable_read_many, blocking=True)
    client.serve("instrument.test", instrument_test, blocking=True)
    client.serve("instrument.call", instrument_call, blocking=True)
    client.serve("instrument.status", instrument_status)


def register_run_ops(client: StationClient, engine) -> None:
    """Run control + step-type introspection (PYTHON_CONTROLLER.md §3.1). engine.start
    accepts iff idle and returns {run_id, accepted}; it spawns the run thread and returns
    at once, so the MQTT loop is never blocked."""
    client.serve("run.start", lambda a: engine.start(a))
    client.serve("run.abort", lambda a: engine.abort())
    client.serve("sequencer.list_test_classes", lambda a: {"test_classes": step_registry.list_test_classes()})


def register_maintenance_ops(client: StationClient, state: dict) -> None:
    """Maintenance mode (PYTHON_CONTROLLER.md §8). The app's health module proxies
    `maintenance.enter/exit` to the controller and reads the state from the retained
    `state/maintenance` topic. Maintenance is PC-wide, so `state` is one dict shared
    across every station's client; each publishes the retained snapshot on its own
    station topic so the app (subscribed per station) sees it.

    Entering maintenance only flips the flag — it hands the operator direct hardware
    control (variable writes are maintenance-gated app-side, §10.4); it does NOT start
    or stop a run. Exiting clears it."""

    def _publish(st: dict) -> None:
        state.clear()
        state.update(st)
        client.publish("state/maintenance", st, retain=True)

    def maintenance_enter(args: dict) -> dict:
        st = {"state": "on", "since": time.time(),
              "by": (args or {}).get("operator"), "reason": (args or {}).get("reason")}
        _publish(st)
        return st

    def maintenance_exit(args: dict) -> dict:
        st = {"state": "off", "since": time.time(),
              "by": (args or {}).get("operator"), "reason": None}
        _publish(st)
        return st

    client.serve("maintenance.enter", maintenance_enter)
    client.serve("maintenance.exit", maintenance_exit)


def register_safety_ops(client: StationClient, safety) -> None:
    """Safety ops (PYTHON_CONTROLLER.md §10). `safety.trip` is one trip source — a manual
    E-stop over the bridge; it only enqueues, the reflex thread does the fan-out (independent
    of the bridge). `safety.clear` un-faults (maintenance-gated app-side, §10.4). The one
    SafetyController is shared across stations, so these are served on every station's client."""
    client.serve("safety.trip", lambda a: safety.trip((a or {}).get("monitor_id") or (a or {}).get("id")))
    client.serve("safety.clear", lambda a: safety.clear((a or {}).get("monitor_id") or (a or {}).get("id")))
    client.serve("safety.status", lambda a: safety.status())

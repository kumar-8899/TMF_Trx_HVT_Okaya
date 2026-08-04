"""Controller entry point (PYTHON_CONTROLLER.md §16 C1).

Loads the one config file, brings up one StationClient per station (LWT + retained
status + hello.echo), and runs until interrupted — publishing each station offline on
the way out. Starts with the app stopped; needs only the broker.

    python -m controller [config.json]     (default: controller.json)
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from pathlib import Path

import controller.step_types  # noqa: F401 — registers the 8 core step types
from controller.bridge.client import StationClient
from controller.config import ConfigError, load_config
from controller.daq import DaqController, register_daq_ops
from controller.instruments import (InstrumentRegistry, StationVariables, check_no_lease,
                                    load_libraries, load_variable_map)
from controller.loop import AsyncLoopThread
from controller.runstate import RunEngine
from controller.serve import register_core_ops, register_run_ops, register_station_ops


def _log(level: str, message: str) -> None:
    print(f"[{level}] {message}", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    config_path = argv[0] if argv else "controller.json"
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        _log("error", f"config: {exc}")
        return 2
    cfg_dir = Path(config_path).resolve().parent

    # Instrument loop + shared registry (one connection per device; §2.1, §9.2).
    loop = AsyncLoopThread()
    loop.start()
    load_libraries(cfg.library_paths, cfg.library_packages, log=_log)
    registry = InstrumentRegistry(loop, log=_log)
    registry.build(cfg.instruments, simulation=cfg.simulation)
    loop.run(registry.connect_all())
    _log("info", f"instruments: {registry.status()}")

    def _emit(client):
        def emit(etype: str, payload: dict) -> None:
            client.publish(f"event/{etype}", {"type": etype, "ts": time.time(),
                                              "trace": f"run:{payload.get('run_id')}", "payload": payload})
        return emit

    def _fetch(client):
        def fetch(recipe_id, version):
            r = client.request("recipe.fetch", {"recipe_id": recipe_id, "version": version})
            if not r.get("ok"):
                raise RuntimeError((r.get("error") or {}).get("message", "recipe.fetch failed"))
            return r.get("result") or {}
        return fetch

    def _diag(client):
        return lambda level, message, **f: client.publish("diag/sequencer",
                                                          {"level": level, "message": message, **f})

    # Load every station's map, then enforce the shared-instrument no-lease rule ACROSS
    # sockets before starting anything (§9.3, fail-closed — a write on a shared device is
    # a silent-wrong-PASS hazard).
    all_stations = [s.station for s in cfg.stations]
    inst_stations = {i["id"]: (i.get("stations") or list(all_stations)) for i in cfg.instruments}
    maps: dict[str, dict] = {}
    for st in cfg.stations:
        vmap = {"signals": {}, "actions": {}}
        if st.variable_map:
            try:
                vmap = load_variable_map(cfg_dir / st.variable_map)
            except Exception as exc:  # noqa: BLE001 — a bad map must not kill the station
                _log("error", f"{st.station} variable map failed: {exc}")
        maps[st.station] = vmap
    violations = check_no_lease(inst_stations, maps)
    if violations:
        for v in violations:
            _log("error", v)
        _log("error", "shared-instrument no-lease rule violated — refusing to start (§9.3)")
        loop.stop()
        return 3

    clients: list[StationClient] = []
    daqs: list[DaqController] = []
    for st in cfg.stations:
        c = StationClient(st.station, host=cfg.broker_host, port=cfg.broker_port, on_log=_log)
        register_core_ops(c)
        variables = StationVariables(st.station, maps[st.station], registry, loop)
        register_station_ops(c, variables, registry, loop)
        engine = RunEngine(st.station, variables=variables, emit=_emit(c), recipe_fetch=_fetch(c),
                           safe_state=(lambda s=st.station: loop.run(registry.safe_state_station(s))),
                           diag=_diag(c), abort_grace_ms=cfg.abort_grace_ms,
                           teardown_timeout_ms=cfg.teardown_timeout_ms)
        register_run_ops(c, engine)
        daq = DaqController(st.station, (lambda sub, p, qos, _c=c: _c.publish(sub, p, qos=qos)),
                            config=cfg.daq, simulation=cfg.simulation)
        register_daq_ops(c, daq)
        daqs.append(daq)
        c.start()
        clients.append(c)
    _log("info", f"controller up: {len(clients)} station(s) on {cfg.broker_host}:{cfg.broker_port}")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        stop.wait()
    finally:
        for d in daqs:
            d.stop_all()
        for c in clients:
            c.stop()
        loop.run(registry.disconnect_all())
        loop.stop()
        _log("info", "controller down")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

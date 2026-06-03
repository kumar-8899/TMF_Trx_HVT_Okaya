"""Live Phase-0 verifier (CORE.md §10) against a *running* broker.

Unlike the pytest suite (which spins an ephemeral broker), this checks the real
thing: it connects to the broker you already have on 127.0.0.1:1883, boots the
app, and walks the §10 criteria printing PASS/FAIL. Watch it in MQTT Explorer at
the same time.

By default it starts the Python reference LabVIEW stub. Pass --no-stub to test
against a real LabVIEW Bridge running on the broker instead.

Run (from backend/, broker already up):
    python -m tools.check_phase0
    python -m tools.check_phase0 --no-stub      # responder = your LabVIEW
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx
from httpx import ASGITransport

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from core.app import create_app  # noqa: E402
from tools.lv_stub import LabviewStub  # noqa: E402

_PASS, _FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    mark = "PASS" if ok else "FAIL"
    if ok:
        _PASS += 1
    else:
        _FAIL += 1
    print(f"  [{mark}] {name}" + (f"  - {detail}" if detail else ""))


async def _until(predicate, timeout=8.0):
    """predicate: a zero-arg callable returning bool (sync or async)."""
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(0.1)
    return False


async def run(host: str, port: int, use_stub: bool) -> int:
    print(f"\nPhase-0 live check against broker {host}:{port}"
          + ("  (stub responder)" if use_stub else "  (real LabVIEW responder)"))

    stub = None
    if use_stub:
        stub = LabviewStub(host, port, station="st1",
                           stream_hz=20.0, value_period=0.2, status_period=0.5)
        await stub.start()

    app = create_app(db_path=":memory:", enable_bridge=True, broker_host=host, broker_port=port)
    frames = {"stream": [], "value": [], "diag": []}
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                # #1 boot
                r = await c.get("/healthz")
                check("#1 app boots, core services up", r.status_code == 200 and r.json()["status"] == "ok")

                # #2 hello loaded
                st = (await c.get("/modules/status")).json()
                check("#2 hello activates through the gate", "hello" in st["loaded"], str(st["loaded"]))

                # #4 readyz green when link online
                async def _readyz_is(code):
                    return (await c.get("/readyz")).status_code == code

                ready = await _until(lambda: _readyz_is(200))
                rj = (await c.get("/readyz")).json()
                check("#4 /readyz green once bridge online", ready and rj["checks"].get("bridge") is True, str(rj["checks"]))

                # #6 stream + value + diag flow
                bridge = app.state.bridge
                bridge.subscribe("stream/ai", lambda t, p: frames["stream"].append(p))
                bridge.subscribe("value/vbus_main", lambda t, p: frames["value"].append(p))
                bridge.subscribe("diag", lambda t, p: frames["diag"].append(p))
                got_stream = await _until(lambda: bool(frames["stream"]))
                got_value = await _until(lambda: bool(frames["value"]))
                got_diag = await _until(lambda: bool(frames["diag"]))
                check("#6 stream/ai frame flows LV->Py", got_stream)
                check("#6 retained value/vbus_main flows", got_value)
                check("#6 diag event flows", got_diag)

                # #5 round-trip
                try:
                    ping = (await c.get("/hello/ping")).json()
                    ok = ping.get("pong") is True and ping.get("echo", {}).get("ok") is True
                    check("#5 /hello/ping round-trips via MQTT", ok, "echo ok" if ok else str(ping))
                except Exception as exc:  # noqa: BLE001
                    check("#5 /hello/ping round-trips via MQTT", False, repr(exc))

                # #7 link offline -> not ready (only when we control the stub)
                if use_stub:
                    await stub.stop()
                    stub = None
                    notready = await _until(lambda: _readyz_is(503))
                    check("#7 stub offline -> /readyz not-ready", notready)
                else:
                    print("  [skip] #7 stop your LabVIEW Bridge and re-check /readyz manually")
    finally:
        if stub is not None:
            await stub.stop()

    print(f"\n{_PASS} passed, {_FAIL} failed\n")
    return 1 if _FAIL else 0


def main() -> None:
    p = argparse.ArgumentParser(description="Live Phase-0 verifier (CORE.md §10)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--no-stub", action="store_true", help="responder is a real LabVIEW Bridge")
    args = p.parse_args()
    rc = asyncio.run(run(args.host, args.port, use_stub=not args.no_stub))
    sys.exit(rc)


if __name__ == "__main__":
    main()

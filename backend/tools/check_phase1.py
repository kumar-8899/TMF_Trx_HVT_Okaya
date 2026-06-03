"""Live Phase-1 verifier (the DAQ/stream + controller vertical) against a running
broker + a real LabVIEW DAQ/controller.

Unlike Phase 0, there is no shipped stub for these ops (daq.*, variable.*, run.*),
so this gates on the real LabVIEW. Boots the app and walks the vertical, printing
PASS/FAIL. Watch tmf/# in MQTT Explorer alongside.

Run (from backend/, broker up, real LabVIEW running):
    python -m tools.check_phase1 --no-stub
    python -m tools.check_phase1 --no-stub --variable vbus_main --write-var setpoint --write-value 12.5
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

_PASS, _FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    _PASS, _FAIL = (_PASS + 1, _FAIL) if ok else (_PASS, _FAIL + 1)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))


async def _until(coro_fn, timeout=8.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if await coro_fn():
            return True
        await asyncio.sleep(0.2)
    return False


async def run(args) -> int:
    print(f"\nPhase-1 live check against broker {args.host}:{args.port}  (real LabVIEW)")
    app = create_app(db_path=":memory:", enable_bridge=True,
                     broker_host=args.host, broker_port=args.port)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            # modules + readiness
            st = (await c.get("/modules/status")).json()
            check("daq + runs loaded", {"daq", "runs"} <= set(st["loaded"]), str(st["loaded"]))
            check("bridge link online", await _until(
                lambda: _code(c, "/readyz", 200)), "")

            # DAQ streaming
            start = await c.post("/instruments/daq/ai/stream/start", json={})
            check("daq.ai.stream.start accepted", start.status_code == 200
                  and start.json().get("ok") is True, _short(start))
            check("stream/ai frames arriving (GET .../ai/latest)", await _until(
                lambda: _code(c, "/instruments/daq/ai/latest", 200)))

            # Variables
            r = await c.get(f"/variables/{args.variable}/value")
            check(f"variable read {args.variable}", r.status_code == 200, _short(r))
            if args.write_var is not None:
                w = await c.put(f"/variables/{args.write_var}/value",
                                json={"value": args.write_value})
                check(f"variable write {args.write_var}", w.status_code == 200, _short(w))

            # Controller run path
            rs = await c.post("/runs/start", json={"recipe": args.recipe})
            check("run.start accepted", rs.status_code == 200 and rs.json().get("ok") is True,
                  _short(rs))
            check("event/run-* -> a run record (GET /runs)", await _until(
                lambda: _nonempty_runs(c)))
            ab = await c.post("/runs/abort", json={})
            check("run.abort accepted", ab.status_code == 200, _short(ab))

    print(f"\n{_PASS} passed, {_FAIL} failed\n")
    return 1 if _FAIL else 0


async def _code(c, path, want) -> bool:
    return (await c.get(path)).status_code == want


async def _nonempty_runs(c) -> bool:
    r = await c.get("/runs")
    return r.status_code == 200 and len(r.json()) > 0


def _short(resp) -> str:
    body = resp.text
    return f"{resp.status_code} {body[:80]}"


def main() -> None:
    p = argparse.ArgumentParser(description="Live Phase-1 verifier (DAQ + controller vertical)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--no-stub", action="store_true",
                   help="responder is a real LabVIEW (no shipped stub covers these ops)")
    p.add_argument("--variable", default="vbus_main")
    p.add_argument("--write-var", default=None)
    p.add_argument("--write-value", type=float, default=0.0)
    p.add_argument("--recipe", default="demo")
    args = p.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

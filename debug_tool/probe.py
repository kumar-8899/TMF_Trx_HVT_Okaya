"""Read-only instrument probes (docs/DEBUG_TOOL.md D4) - relayed through the RUNNING app.

An instrument has one client (the controller owns the link), so the tool cannot talk to hardware itself: it asks the app's own
Test Bench endpoint (`POST /variables/instances/{id}/call`) with the core login token the developer supplied. No new roles or
permissions - the core's existing gate applies on top of the operator's approval.

What a probe may call is decided from the app's own catalog, never from the caller's word:
  allowed  `identify`, and any method `GET /variables/capabilities` marks `kind: "read"` for a capability that instance declares
  refused  everything else - set/toggle/enum/action kinds, `safe_state`, `emergency_disable`, unknown methods
Also: refused while a test run is active (a probe must never disturb a measurement), one call in flight, a minimum spacing between
calls, a 10 s timeout, scalar arguments only.
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time
from typing import Any

ALWAYS_ALLOWED = ("identify",)
NEVER = ("safe_state", "emergency_disable")
MIN_SPACING_S = 0.5
PROBE_SPACING_S = 1.0
CALL_TIMEOUT_S = 10.0
MAX_SAMPLES = 60
MAX_POLL_BUDGET_S = 180.0


class ProbeRefused(Exception):
    """Policy said no (not a read method, run active, unknown instance...). Nothing was sent to the instrument."""


class ProbeFailed(Exception):
    """The relay or the instrument failed; the message carries the app's own structured error."""


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, math.ceil(p / 100 * len(sorted_vals)) - 1))
    return sorted_vals[k]


class InstrumentProbe:
    def __init__(self, engine, *, clock=time.monotonic, sleep=asyncio.sleep) -> None:
        self.engine = engine
        self._clock, self._sleep = clock, sleep
        self._lock = asyncio.Lock()
        self._last_call = -1e9

    # ------------------------------------------------------------------ policy
    async def _get(self, path: str, token: str | None):
        try:
            return await self.engine._core("GET", path, token)
        except (RuntimeError, PermissionError) as exc:
            raise ProbeFailed(str(exc)) from exc

    async def allowed_methods(self, instance_id: str, token: str | None) -> dict:
        insts = await self._get("/variables/instances", token)
        inst = next((i for i in (insts if isinstance(insts, list) else []) if i.get("id") == instance_id), None)
        if inst is None:
            known = [i.get("id") for i in insts] if isinstance(insts, list) else []
            raise ProbeRefused(f"no instrument instance {instance_id!r} (known: {known})")
        if inst.get("state") == "skipped":
            raise ProbeRefused(f"{instance_id} is skipped by the app ({inst.get('reason')})")
        cat = await self._get("/variables/capabilities", token)
        caps = (cat or {}).get("capabilities", {})
        reads: dict[str, dict] = {}
        for cap in inst.get("capabilities") or []:
            for m in (caps.get(cap) or {}).get("methods", []):
                if m.get("kind") == "read":
                    reads[m["method"]] = m
        return {"instance": inst, "reads": reads}

    def check(self, method: str, args: list, allowed: dict) -> None:
        if method in NEVER:
            raise ProbeRefused(f"{method} cuts instrument outputs - it is never available to a probe")
        if method not in ALWAYS_ALLOWED and method not in allowed["reads"]:
            raise ProbeRefused(f"{method!r} is not a read-only method of {allowed['instance'].get('id')} - allowed: "
                               f"{sorted(ALWAYS_ALLOWED + tuple(allowed['reads']))}")
        if len(args) > 4 or any(not isinstance(a, (int, float, str, bool)) or (isinstance(a, str) and len(a) > 64) for a in args):
            raise ProbeRefused("arguments must be at most 4 short scalars (number, bool, text)")

    def refuse_if_running(self) -> None:
        if self.engine.run_active():
            raise ProbeRefused("a test run is in progress - a probe could disturb the measurement; try again between runs")

    # ------------------------------------------------------------------ calls
    async def _one(self, instance_id: str, method: str, args: list, token: str | None, spacing: float) -> tuple[Any, float]:
        async with self._lock:
            wait = spacing - (self._clock() - self._last_call)
            if wait > 0:
                await self._sleep(wait)
            t0 = self._clock()
            try:
                reply = await asyncio.wait_for(self.engine._core("POST", f"/variables/instances/{instance_id}/call", token,
                                                                 {"method": method, "args": args}), CALL_TIMEOUT_S)
            except asyncio.TimeoutError as exc:
                raise ProbeFailed(f"no answer from {instance_id} within {CALL_TIMEOUT_S:g} s") from exc
            except (RuntimeError, PermissionError) as exc:
                raise ProbeFailed(str(exc)) from exc
            finally:
                self._last_call = self._clock()
            return (reply or {}).get("result"), round((self._clock() - t0) * 1000.0, 1)

    async def probe(self, instance_id: str, method: str, args: list | None, token: str | None) -> dict:
        args = list(args or [])
        self.refuse_if_running()
        allowed = await self.allowed_methods(instance_id, token)
        self.check(method, args, allowed)
        self.refuse_if_running()
        result, ms = await self._one(instance_id, method, args, token, PROBE_SPACING_S)
        return {"instance": instance_id, "method": method, "args": args, "result": result, "latency_ms": ms,
                "state": allowed["instance"].get("state"), "simulated": allowed["instance"].get("simulated")}

    async def poll(self, instance_id: str, method: str, args: list | None, token: str | None, *, samples: int = 10,
                   interval_s: float = 1.0, progress=None) -> dict:
        args = list(args or [])
        samples = max(1, min(int(samples), MAX_SAMPLES))
        interval = max(MIN_SPACING_S, min(float(interval_s), 10.0))
        self.refuse_if_running()
        allowed = await self.allowed_methods(instance_id, token)
        self.check(method, args, allowed)
        values: list[Any] = []
        lat: list[float] = []
        dropouts: list[dict] = []
        t_start = self._clock()
        stopped = None
        for i in range(samples):
            if self.engine.run_active():
                stopped = "a test run started - polling stopped so it could not disturb the measurement"
                break
            if self._clock() - t_start > MAX_POLL_BUDGET_S:
                stopped = f"time budget of {MAX_POLL_BUDGET_S:g} s reached"
                break
            try:
                v, ms = await self._one(instance_id, method, args, token, interval)
                values.append(v)
                lat.append(ms)
            except ProbeFailed as exc:
                dropouts.append({"sample": i, "error": str(exc)[:200]})
            if progress:
                progress(i + 1, samples)
        nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        out: dict = {"instance": instance_id, "method": method, "args": args, "requested": samples, "ok_samples": len(values),
                     "dropouts": len(dropouts), "dropout_detail": dropouts[:10], "values": values[:MAX_SAMPLES],
                     "latency_ms": ({"p50": _pct(sorted(lat), 50), "p95": _pct(sorted(lat), 95), "max": max(lat)} if lat else None)}
        if nums:
            out["stats"] = {"min": min(nums), "max": max(nums), "mean": statistics.fmean(nums),
                            "stddev": statistics.pstdev(nums) if len(nums) > 1 else 0.0, "n": len(nums)}
        elif values:
            out["note"] = "results are not numeric - no statistics computed"
        if stopped:
            out["stopped_early"] = stopped
        return out

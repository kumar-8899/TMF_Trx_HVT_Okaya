"""The action tools that touch the client PC itself: scripts, files, instrument probes. Each waits for a human.

What the operator reads on the approval card is the whole request - the full script text, the path, the instrument + method +
arguments + sample count - so approving means exactly that and nothing else. Requests the policy would refuse anyway (a write
method, a path outside the install, a run in progress for a probe) are refused BEFORE a card is raised: the person at the
bench is only ever asked about things that could actually happen.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

from debug_tool import files as filesmod
from debug_tool import scripts as scriptsmod
from debug_tool.consent import Decision
from debug_tool.mcp_server import Host, _progress


class RunActive(Exception):
    pass


def register(h: Host) -> None:
    eng = h.engine
    T = h.tool

    @T("bench_run_script", "Run a script on the client PC", action=True, destructive=True)
    async def bench_run_script(ctx: Context, interpreter: str, script: str, timeout_s: int = 60,
                               args: list[str] | None = None) -> dict[str, Any]:
        """Run ONE custom script (powershell | cmd | python) on the client PC after the operator reads and approves its exact text.
        Runs unelevated, scrubbed environment, one at a time, timeout <= 300 s, output capped. Refused during a test run unless the
        approver ticks 'allow during a test'. Tell the engineer what the script does before calling."""
        sha = scriptsmod.sha256_of(interpreter, script)                           # also validates interpreter / empty script
        argv_tail = scriptsmod.check_args(args)
        timeout = scriptsmod.clamp_timeout(timeout_s)
        details: dict[str, Any] = {"interpreter": interpreter, "script": script, "sha256": sha, "timeout_s": timeout,
                                   "args": argv_tail, "runs_as": "the Windows user running the Debug Tool (no elevation)",
                                   "run_active_now": eng.run_active()}
        if interpreter == "python":
            details["python"] = (await asyncio.to_thread(eng.pyenv.status))["will_use"]
        if eng.run_active():
            details["warning"] = "A TEST RUN IS IN PROGRESS. Approve only if the script cannot disturb it; ticking 'allow during a test' is required."
        lines = len(script.splitlines())
        summary = f"Run a {interpreter} script ({lines} line{'s' if lines != 1 else ''}, sha256 {sha[:12]}) on this PC - timeout {timeout} s"

        async def run(d: Decision) -> dict:
            if eng.run_active() and not (d.extra.get("allow_during_run") or h.sharing.allow_during_run):
                raise RunActive("a test run is in progress and the approver did not allow scripts during a test - nothing was run")
            beat = asyncio.create_task(_progress(ctx, timeout, "script running on the client PC"))
            try:
                return await eng.scripts.run(interpreter, script, timeout_s=timeout, args=argv_tail, approved_by=d.by)
            finally:
                beat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beat
        return await h.action(ctx, "bench_run_script", "run_script", summary, details, run, untrusted=True)

    @T("bench_read_file", "Read a text file from the install", action=True)
    async def bench_read_file(ctx: Context, path: str, tail_lines: int | None = None) -> dict[str, Any]:
        """Read one text file under the app's install/state folders (<= 64 KB, secret-looking values masked, binaries refused).
        Waits for approval."""
        roots = [r for r in (eng.app.state_root, eng.app.bundle_root) if r]
        if not roots:
            return h.fail("NoInstall", "no app install was found, so there is nothing to read")
        p = Path(path)
        if not p.is_absolute():
            p = next((r / p for r in roots if (r / p).exists()), roots[0] / p)
        if not filesmod.under(p, roots):                                          # refuse before bothering the operator
            raise filesmod.FileRefused(f"{path!s} is outside the app's install/state folders - only those can be read")
        if not p.is_file():
            raise filesmod.FileRefused(f"{p} is not a file (or does not exist)")
        tail = max(1, min(int(tail_lines), 2000)) if tail_lines else None

        async def run(d: Decision) -> dict:
            return await asyncio.to_thread(filesmod.read_text, p, roots, tail_lines=tail)
        return await h.action(ctx, "bench_read_file", "read_file", f"Read {p}" + (f" (last {tail} lines)" if tail else ""),
                              {"path": str(p), "tail_lines": tail, "size_bytes": p.stat().st_size,
                               "note": "secret-looking values are masked in what is returned"}, run, untrusted=True)

    async def _preflight(instance_id: str, method: str, args: list, token: str | None):
        if not token:
            raise PermissionError("instrument probes go through the app's Test Bench endpoint and need a core login token "
                                  "(header X-Core-Token)")
        eng.probe.refuse_if_running()
        allowed = await eng.probe.allowed_methods(instance_id, token)
        eng.probe.check(method, args, allowed)
        return allowed

    @T("bench_instrument_probe", "Read one value from an instrument", action=True, destructive=True)
    async def bench_instrument_probe(ctx: Context, instance_id: str, method: str, args: list[Any] | None = None) -> dict[str, Any]:
        """Send ONE read-only command to one instrument through the running app (identify, or a method the app's catalog marks
        'read'). Never set/toggle/enum/action, never during a test run. Needs X-Core-Token. Waits for approval."""
        token = h.core_token(ctx)
        a = list(args or [])
        allowed = await _preflight(instance_id, method, a, token)
        summary = f"Read-only: send {method}({', '.join(map(str, a))}) to instrument '{instance_id}'"

        async def run(d: Decision) -> dict:
            return await eng.probe.probe(instance_id, method, a, token)
        return await h.action(ctx, "bench_instrument_probe", "instrument_probe", summary,
                              {"instance": instance_id, "method": method, "args": a, "kind": "read-only",
                               "state": allowed["instance"].get("state"), "simulated": allowed["instance"].get("simulated")}, run)

    @T("bench_instrument_poll", "Poll an instrument and summarise", action=True, destructive=True)
    async def bench_instrument_poll(ctx: Context, instance_id: str, method: str, args: list[Any] | None = None,
                                    samples: int = 10, interval_s: float = 1.0) -> dict[str, Any]:
        """Poll one read-only method up to 60 times (>= 0.5 s apart) and return min/max/mean/stddev, latency and dropouts - to
        see noise or a flaky link. Same rules as bench_instrument_probe. Waits for approval."""
        token = h.core_token(ctx)
        a = list(args or [])
        allowed = await _preflight(instance_id, method, a, token)
        n = max(1, min(int(samples), 60))
        every = max(0.5, min(float(interval_s), 10.0))
        summary = f"Read-only: poll {method}({', '.join(map(str, a))}) on instrument '{instance_id}' x{n} every {every:g} s (~{int(n * every)} s)"

        async def run(d: Decision) -> dict:
            beat = asyncio.create_task(_progress(ctx, n * every, f"polling {instance_id}.{method}"))
            try:
                return await eng.probe.poll(instance_id, method, a, token, samples=n, interval_s=every)
            finally:
                beat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await beat
        return await h.action(ctx, "bench_instrument_poll", "instrument_poll", summary,
                              {"instance": instance_id, "method": method, "args": a, "samples": n, "interval_s": every,
                               "kind": "read-only", "state": allowed["instance"].get("state")}, run)

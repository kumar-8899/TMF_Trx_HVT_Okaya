"""`tmf-debug-tool selftest` - does the tool work on THIS PC, end to end, without touching the real app?

It builds a throwaway fake install in a temp folder, starts the tool on a private port and drives it exactly as Claude Code and the
operator would: sharing off/on, bearer token, the MCP handshake, a passive tool, an action that blocks until a human approves,
a denial, a timeout, a PowerShell script and a Python script after approval, the one-click bundle, the analyser, Stop.

Two uses: the release gate for the frozen build (`deploy/verify-debug-tool.ps1`), and a field check on a client PC - it is the first
thing to run when antivirus, execution policy, a missing PowerShell, a blocked port or a locked-down profile might stop the tool
from doing its job. Nothing here reads or changes the real app.
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import json
import os
import platform
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

PASS, FAIL, SKIP, INFO = "pass", "fail", "skip", "info"


@dataclass
class Step:
    name: str
    status: str
    detail: str = ""
    ms: int = 0


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _fake_install(root: Path) -> None:
    (root / "run.dist").mkdir(parents=True)
    (root / "run.dist" / "RELEASE.json").write_text(json.dumps({"product": "selftest", "version": "0.0.0", "framework_version": "1.0.0"}))
    (root / "config").mkdir()
    (root / "config" / "app.json").write_text(json.dumps({"stations": ["st1"], "debug": {"enabled": False}}))
    (root / "data").mkdir()
    con = sqlite3.connect(root / "data" / "tmf.sqlite")
    con.execute("CREATE TABLE records (id TEXT, type TEXT, ts REAL, station TEXT, source_version TEXT, summary TEXT, data TEXT, "
                "PRIMARY KEY (type, id))")
    con.commit()
    con.close()


def _is_admin() -> bool | None:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())                          # type: ignore[attr-defined]
    except Exception:                                                               # noqa: BLE001
        return None


async def selftest_async(*, require_python: bool = False, tool_dir: Path | None = None, log=None) -> list[Step]:
    import httpx
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    from debug_tool import VERSION
    from debug_tool.app import build_app, create_runtime
    from debug_tool.appinfo import discover
    from debug_tool.engine import EngineConfig
    from debug_tool.mcp_server import ACTION_TOOLS, PASSIVE_TOOLS

    steps: list[Step] = []

    def add(name: str, status: str, detail: str = "", t0: float | None = None) -> Step:
        s = Step(name, status, detail, int((time.time() - t0) * 1000) if t0 else 0)
        steps.append(s)
        if log:
            log(f"  {s.status.upper():5} {s.name}" + (f" - {s.detail}" if s.detail else ""))
        return s

    admin = _is_admin()
    add("environment", INFO, f"tool {VERSION} - {'frozen' if getattr(sys, 'frozen', False) else 'source'} - python {platform.python_version()} - "
        f"{platform.platform()} - user {getpass.getuser()} - powershell {'found' if shutil.which('powershell') else 'NOT found'}")
    if admin:
        add("not elevated", FAIL, "the tool is running as administrator: approved scripts would also run elevated. Start it as the "
            "normal operator account.")
    else:
        add("not elevated", PASS if admin is False else INFO, "scripts run with the operator's normal rights" if admin is False else "could not tell")

    tmp = tempfile.TemporaryDirectory(prefix="tmf-selftest-", ignore_cleanup_errors=True)
    root = Path(tmp.name) / "deploy"
    _fake_install(root)
    port = _free_port()
    cfg = EngineConfig(app=discover(root, processes=lambda: []), data_dir=Path(tmp.name) / "tool", port=port, tool_dir=tool_dir,
                       in_app_probe=lambda p: False)
    engine_kw = {}
    if sys.platform == "win32" and not isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop):
        async def idle_subscriber(ingestor, host, bport, *, on_state=None):      # aiomqtt cannot run on the Proactor loop (tests only;
            await asyncio.sleep(3600)                                              # the CLI always selects the selector loop)
        engine_kw["subscriber"] = idle_subscriber
    rt = create_runtime(cfg, approval_timeout_s=3.0, **engine_kw)
    server = uvicorn.Server(uvicorn.Config(build_app(rt, port=port, heartbeat_s=1.0), host="127.0.0.1", port=port, log_level="error"))
    task = asyncio.create_task(server.serve())
    base = f"http://127.0.0.1:{port}"
    op = {"X-Operator-Key": rt.operator_key}
    try:
        t0 = time.time()
        for _ in range(150):
            if server.started:
                break
            await asyncio.sleep(0.1)
        if not server.started:
            add("start", FAIL, f"the tool did not start listening on 127.0.0.1:{port} (a firewall or security product may be blocking it)", t0)
            return steps
        add("start", PASS, f"listening on 127.0.0.1:{port}", t0)
        await asyncio.sleep(0.2)

        async with httpx.AsyncClient(timeout=20) as c:
            t0 = time.time()
            r = await c.get(f"{base}/debug/health", headers={"Authorization": "Bearer x"})
            add("off by default", PASS if r.status_code == 403 else FAIL, f"remote access while sharing is off -> {r.status_code} (want 403)", t0)

            t0 = time.time()
            token = (await c.post(f"{base}/operator/sharing/start", json={"hours": 1}, headers=op)).json()["token"]
            bad = await c.get(f"{base}/debug/health", headers={"Authorization": "Bearer wrong"})
            good = await c.get(f"{base}/debug/health", headers={"Authorization": f"Bearer {token}"})
            add("token", PASS if (bad.status_code, good.status_code) == (401, 200) else FAIL,
                f"wrong token -> {bad.status_code} (want 401), right token -> {good.status_code} (want 200)", t0)
            nokey = await c.get(f"{base}/operator/approvals", headers={"Authorization": f"Bearer {token}"})
            add("token cannot approve", PASS if nokey.status_code == 401 else FAIL, f"operator endpoint with only the MCP token -> {nokey.status_code} (want 401)")

            async def pending() -> list[dict]:
                for _ in range(100):
                    p = (await c.get(f"{base}/operator/approvals", headers=op)).json()["pending"]
                    if p:
                        return p
                    await asyncio.sleep(0.1)
                return []

            async def decide(approve: bool) -> None:
                p = await pending()
                if p:
                    await c.post(f"{base}/operator/approvals/{p[0]['id']}", json={"approve": approve}, headers=op)

            try:
                async with streamablehttp_client(f"{base}/mcp", headers={"Authorization": f"Bearer {token}"}, terminate_on_close=False) as (r_, w_, _):
                    async with ClientSession(r_, w_) as s:
                        t0 = time.time()
                        await s.initialize()
                        names = {t.name for t in (await s.list_tools()).tools}
                        missing = sorted((set(PASSIVE_TOOLS) | set(ACTION_TOOLS)) - names)
                        add("mcp handshake", PASS if not missing else FAIL, f"{len(names)} tools" + (f"; MISSING {missing}" if missing else ""), t0)

                        t0 = time.time()
                        h = json.loads((await s.call_tool("bench_health", {})).content[0].text)
                        add("passive tool", PASS if h.get("ok") else FAIL, "bench_health answered without any approval", t0)

                        t0 = time.time()
                        call = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "selftest"}))
                        await asyncio.sleep(0.5)
                        waited = not call.done()
                        await decide(True)
                        out = json.loads((await asyncio.wait_for(call, 20)).content[0].text)
                        add("action waits for approval", PASS if waited and out.get("decision") == "approved" else FAIL,
                            f"blocked until approved: {waited}; result: {out.get('decision')}", t0)

                        t0 = time.time()
                        call = asyncio.create_task(s.call_tool("bench_capture_start", {"name": "selftest-deny"}))
                        await decide(False)
                        out = json.loads((await asyncio.wait_for(call, 20)).content[0].text)
                        add("deny", PASS if out.get("decision") == "denied" else FAIL, f"result: {out.get('decision')}", t0)

                        t0 = time.time()
                        out = json.loads((await asyncio.wait_for(s.call_tool("bench_capture_start", {"name": "selftest-timeout"}), 30)).content[0].text)
                        add("no answer = denied", PASS if out.get("decision") == "timeout" else FAIL, f"result: {out.get('decision')} (after 3 s)", t0)

                        if shutil.which("powershell"):
                            t0 = time.time()
                            call = asyncio.create_task(s.call_tool("bench_run_script", {"interpreter": "powershell", "timeout_s": 60,
                                                                                         "script": "Write-Output 'selftest-ps-ok'"}))
                            await decide(True)
                            out = json.loads((await asyncio.wait_for(call, 90)).content[0].text)
                            ok = out.get("ok") and "selftest-ps-ok" in (out.get("data") or {}).get("stdout", "")
                            add("powershell script", PASS if ok else FAIL, "ran after approval" if ok else f"{out.get('error') or out.get('message') or out.get('data')}", t0)
                        else:
                            add("powershell script", FAIL, "powershell.exe was not found on this PC")

                        t0 = time.time()
                        py_status = await asyncio.to_thread(rt.engine.pyenv.status)
                        if py_status["will_use"] == "none":
                            add("python script", FAIL if require_python else SKIP,
                                "no Python on this PC and no bundled interpreter (python-embed*.zip) next to the tool - Python scripts cannot run", t0)
                        else:
                            call = asyncio.create_task(s.call_tool("bench_run_script", {"interpreter": "python", "timeout_s": 120,
                                                                                         "script": "print('selftest-py-ok')"}))
                            await decide(True)
                            out = json.loads((await asyncio.wait_for(call, 150)).content[0].text)
                            ok = out.get("ok") and "selftest-py-ok" in (out.get("data") or {}).get("stdout", "")
                            kind = ((out.get("data") or {}).get("python") or {}).get("kind")
                            if ok and require_python and kind != "bundled":
                                add("python script", FAIL, f"ran on the {kind} interpreter, but a release must carry and run the BUNDLED one "
                                    "(python-embed*.zip missing from the package?)", t0)
                            else:
                                add("python script", PASS if ok else FAIL,
                                    f"ran on the {kind} interpreter" if ok else f"{out.get('error') or out.get('message')}", t0)
            except Exception as exc:                                                # noqa: BLE001 - a broken step is a finding, not a crash
                add("mcp session", FAIL, f"{type(exc).__name__}: {exc}")

            t0 = time.time()
            try:
                res = await rt.engine.export_bundle(rows=100, integrity=False, register=False)
                a = await asyncio.to_thread(rt.engine.analyze_bundle, res["path"])
                add("collect + analyze", PASS if a.get("markdown") else FAIL, f"{res['files']} files, {res['bytes'] // 1024} KB, analysed", t0)
            except Exception as exc:                                                # noqa: BLE001
                add("collect + analyze", FAIL, f"{type(exc).__name__}: {exc}", t0)

            t0 = time.time()
            await c.post(f"{base}/operator/sharing/stop", headers=op)
            r = await c.get(f"{base}/debug/health", headers={"Authorization": f"Bearer {token}"})
            add("stop", PASS if r.status_code == 403 else FAIL, f"after Stop the old token -> {r.status_code} (want 403)", t0)

        host, bport = rt.engine.app.broker()
        reachable = await asyncio.to_thread(lambda: __import__("debug_tool.engine", fromlist=["tcp_listening"]).tcp_listening(host, bport))
        add("broker (info)", INFO, f"{host}:{bport} {'is reachable' if reachable else 'is not reachable here - live MQTT will show disconnected until the app is running'}")
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, 15)
        tmp.cleanup()
    return steps


def run(*, require_python: bool = False, tool_dir: Path | None = None, log=print) -> list[Step]:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(selftest_async(require_python=require_python, tool_dir=tool_dir, log=log))


def render(steps: list[Step]) -> str:
    bad = [s for s in steps if s.status == FAIL]
    lines = [f"{'PASS' if not bad else 'FAIL'}: {sum(s.status == PASS for s in steps)} passed, {len(bad)} failed, "
             f"{sum(s.status == SKIP for s in steps)} skipped"]
    lines += [f"  {s.status.upper():5} {s.name:26} {s.detail}" for s in steps]
    return "\n".join(lines)


def to_json(steps: list[Step]) -> str:
    return json.dumps({"ok": not any(s.status == FAIL for s in steps), "steps": [asdict(s) for s in steps]}, indent=2)

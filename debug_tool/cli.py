"""tmf-debug-tool - the command line (docs/DEBUG_TOOL.md).

  on the client PC
    serve                          start the tool (live collectors + MCP endpoint + operator API)         [connected mode]
    share / stop / approvals / approve <id> / deny <id>
                                   the operator's controls from a second terminal (the UI does the same through the same API)
    collect [out.zip]              one-click diagnostics bundle -> your Desktop                            [air-gapped mode]
  on the developer's machine
    analyze <bundle.zip>           read a bundle back -> .debug/<name>-<stamp>/analysis.md + analysis.json
    kit collect|script             make the files an engineer carries to the client PC
    mcp-stdio                      stdio MCP (bench_collect_kit / bench_script_kit / bench_analyze_bundle) for Claude Code
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from debug_tool._paths import ensure_source_paths

ensure_source_paths()

from debug_tool import VERSION  # noqa: E402

DEFAULT_PORT = 8010


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "TMF-Debug-Tool" if base else Path.home() / ".tmf-debug-tool"


def operator_file(data_dir: Path) -> Path:
    return data_dir / "operator.json"


# ------------------------------------------------------------------------------------------------ serve

def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from debug_tool.app import build_app, create_runtime
    from debug_tool.appinfo import discover
    from debug_tool.engine import EngineConfig

    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    app_info = discover(args.state_dir, tool_dir=Path(sys.argv[0]).resolve().parent)
    print(f"tmf-debug-tool {VERSION}")
    if app_info.found:
        print(f"app:   {app_info.product or 'app'} {app_info.app_version or '?'} at {app_info.state_root}  ({app_info.source})")
    else:
        print(f"app:   NOT FOUND ({app_info.source}) - running with defaults (broker 127.0.0.1:1883); pass --state-dir <deploy root>")
    cfg = EngineConfig(app=app_info, data_dir=data_dir, bind_host=args.bind, port=args.port, force_mode=args.mode)
    rt = create_runtime(cfg, approval_timeout_s=args.approval_timeout)
    app = build_app(rt, bind_host=args.bind, port=args.port)
    of = operator_file(data_dir)
    of.write_text(json.dumps({"host": args.bind, "port": args.port, "key": rt.operator_key, "pid": os.getpid()}), encoding="utf-8")
    print(f"data:  {data_dir}")
    print(f"serve: http://{args.bind}:{args.port}   (sharing is OFF until the operator turns it on:  tmf-debug-tool share)")
    server = uvicorn.Server(uvicorn.Config(app, host=args.bind, port=args.port, log_level="warning"))

    async def main() -> None:
        await server.serve()

    if sys.platform == "win32":                                    # aiomqtt needs the selector loop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    finally:
        of.unlink(missing_ok=True)
    return 0


# ------------------------------------------------------------------------------------------------ operator (second terminal)

def _operator(args: argparse.Namespace):
    import httpx
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    of = operator_file(data_dir)
    if not of.is_file():
        print(f"no running tool found ({of} missing) - start it with:  tmf-debug-tool serve", file=sys.stderr)
        raise SystemExit(2)
    info = json.loads(of.read_text(encoding="utf-8"))
    return httpx.Client(base_url=f"http://{info['host']}:{info['port']}", headers={"X-Operator-Key": info["key"]}, timeout=10.0)


def _call(args, method: str, path: str, body: dict | None = None) -> dict:
    with _operator(args) as c:
        r = c.request(method, path, json=body)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        print(f"{path}: {r.status_code} {detail}", file=sys.stderr)
        raise SystemExit(1)
    return r.json()


def cmd_share(args: argparse.Namespace) -> int:
    out = _call(args, "POST", "/operator/sharing/start", {"hours": args.hours, "allow_during_run": args.allow_during_run, "name": args.name})
    print(f"Sharing is ON for {out['expires_in_s'] // 60} min (token fingerprint {out['fingerprint']}).")
    print("Give the developer this command - the token is shown ONCE and is not stored:\n")
    print(out["claude_command"])
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    out = _call(args, "POST", "/operator/sharing/stop")
    print(f"Sharing stopped. {out['denied_pending']} pending request(s) denied.")
    return 0


def cmd_approvals(args: argparse.Namespace) -> int:
    out = _call(args, "GET", "/operator/approvals")
    if not out["pending"]:
        print("nothing waiting for approval")
    for p in out["pending"]:
        print(f"[{p['id']}] {p['kind']}  waiting {p['age_s']}s of {int(p['timeout_s'])}s\n    {p['summary']}")
        for k, v in p["details"].items():
            text = v if isinstance(v, str) else json.dumps(v)
            print(f"    {k}: {text}")
    return 0


def cmd_decide(args: argparse.Namespace, approve: bool) -> int:
    out = _call(args, "POST", f"/operator/approvals/{args.id}", {"approve": approve, "allow_during_run": getattr(args, "allow_during_run", False)})
    print(f"{args.id}: {out['decision']}")
    return 0


# ------------------------------------------------------------------------------------------------ collect / analyze / kits

def _desktop() -> Path:
    d = Path.home() / "Desktop"
    return d if d.is_dir() else Path.cwd()


def cmd_collect(args: argparse.Namespace) -> int:
    from debug_server.export import export_bundle

    from debug_tool.appinfo import discover
    app_info = discover(args.state_dir, tool_dir=Path(sys.argv[0]).resolve().parent)
    if not app_info.found:
        print(f"collect: no app install found ({app_info.source}) - pass --state-dir <deploy root>", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else _desktop()
    if out.is_dir() or not out.suffix:
        out = out / f"tmf-debug-{os.environ.get('COMPUTERNAME', 'station')}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    m = export_bundle(out, state_root=app_info.state_root, rows=args.rows, bundle_root_override=app_info.bundle_root,
                      integrity=not args.no_integrity)
    total = sum(f["bytes"] for f in m["files"])
    print(f"collect: {len(m['files'])} file(s), {total / 1024:.0f} KB -> {out.resolve()}")
    for miss in m["missing"]:
        print(f"  missing: {miss}")
    print("Send this ONE file to the developer (delete it after the case; it can contain operator names and serial numbers).")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from tmf_debug.bundle import BundleError, analyze
    try:
        a = analyze(args.zip, args.out, name=args.name)
    except BundleError as exc:
        print(f"analyze: {exc}", file=sys.stderr)
        return 2
    print("\n".join(a["look_here_first"]) or "nothing alarming found")
    print(f"\nanalysis: {a['paths']['analysis_md']}\nfolder:   {a['paths']['folder']}")
    return 0


def cmd_kit(args: argparse.Namespace) -> int:
    from debug_tool import kits
    if args.kind == "collect":
        out = kits.collect_kit(args.out or ".debug/kit-collect")
    else:
        text = Path(args.script).read_text(encoding="utf-8")
        out = kits.script_kit(text, args.interpreter, args.out or ".debug/kit-script", timeout_s=args.timeout,
                              name=Path(args.script).stem)
    print(json.dumps(out, indent=2))
    return 0


def cmd_mcp_stdio(args: argparse.Namespace) -> int:
    from debug_tool.local_mcp import run_stdio
    run_stdio(args.workdir)
    return 0


# ------------------------------------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tmf-debug-tool", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"tmf-debug-tool {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp, state=False):
        sp.add_argument("--data-dir", default=None, help="the tool's own folder (default %%LOCALAPPDATA%%\\TMF-Debug-Tool)")
        if state:
            sp.add_argument("--state-dir", default=None, help="deploy root (the folder that contains run.dist); default: auto-detect")

    sp = sub.add_parser("serve", help="start the tool (connected mode)")
    common(sp, True)
    sp.add_argument("--bind", default="127.0.0.1", help="ONE address to listen on (127.0.0.1, or the PC's VPN/LAN address) - never 0.0.0.0")
    sp.add_argument("--port", type=int, default=DEFAULT_PORT)
    sp.add_argument("--mode", choices=("own", "attach"), default=None, help="recorder mode (default: auto - attach if the in-app recorder is running)")
    sp.add_argument("--approval-timeout", type=float, default=120.0, help="seconds an action waits for a human before it is denied")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("share", help="operator: turn sharing ON and print the command for the developer")
    common(sp)
    sp.add_argument("--hours", type=float, default=4.0)
    sp.add_argument("--name", default=None, help="name for the MCP server in Claude Code")
    sp.add_argument("--allow-during-run", action="store_true")
    sp.set_defaults(func=cmd_share)

    sp = sub.add_parser("stop", help="operator: stop sharing now (denies everything pending)")
    common(sp)
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("approvals", help="operator: list requests waiting for a decision")
    common(sp)
    sp.set_defaults(func=cmd_approvals)

    for name, flag in (("approve", True), ("deny", False)):
        sp = sub.add_parser(name, help=f"operator: {name} one waiting request")
        common(sp)
        sp.add_argument("id")
        if flag:
            sp.add_argument("--allow-during-run", action="store_true", help="also allow it while a test is running")
        sp.set_defaults(func=lambda a, f=flag: cmd_decide(a, f))

    sp = sub.add_parser("collect", help="one-click diagnostics bundle (air-gapped mode)")
    common(sp, True)
    sp.add_argument("out", nargs="?", default=None, help="output zip or folder (default: your Desktop)")
    sp.add_argument("--rows", type=int, default=5000)
    sp.add_argument("--no-integrity", action="store_true")
    sp.set_defaults(func=cmd_collect)

    sp = sub.add_parser("analyze", help="read a bundle zip back -> analysis.md + analysis.json")
    sp.add_argument("zip")
    sp.add_argument("--out", default=".debug")
    sp.add_argument("--name", default=None)
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("kit", help="make a kit for an engineer to carry to the client PC")
    sp.add_argument("kind", choices=("collect", "script"))
    sp.add_argument("--script", default=None, help="(script kit) the script file to wrap")
    sp.add_argument("--interpreter", choices=("powershell", "cmd", "python"), default="powershell")
    sp.add_argument("--timeout", type=int, default=60)
    sp.add_argument("--out", default=None)
    sp.set_defaults(func=cmd_kit)

    sp = sub.add_parser("mcp-stdio", help="stdio MCP server for Claude Code (kits + analyse; air-gapped)")
    sp.add_argument("--workdir", default=".", help="kits and analyses are written under this folder")
    sp.set_defaults(func=cmd_mcp_stdio)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "kit" and args.kind == "script" and not args.script:
        print("kit script: --script <file> is required", file=sys.stderr)
        return 2
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

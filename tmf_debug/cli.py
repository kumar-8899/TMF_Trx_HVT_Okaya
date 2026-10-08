"""tmf-debug — the command a developer (or Claude Code) invokes (REMOTE_DEBUG.md §8).

    tmf-debug watch  --host bench1 [--module daq --level warning --topic value --grep vbus]
    tmf-debug pull   --host bench1 [--since <seq> | --last-run | --run <id>]
    tmf-debug health --host bench1
    tmf-debug level  --host bench1 --module daq --set debug        (PR-F)
    tmf-debug snapshots --host bench1 [--get <id>]                 (PR-E)
    tmf-debug digest <file.jsonl>                                  (PR-B)
    tmf-debug why    --host bench1 --last-run                      (PR-G)
    tmf-debug export [out.zip] [--state-dir <deploy root>]          (air-gapped bench: one zip)

Everything lands in `.debug/` at the app-repo root (gitignored). The app CLAUDE.md
documents this so Claude Code always knows where to look.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from tmf_debug.client import DEFAULT_PORT, DebugClient

OUT_DIR = Path(".debug")


# --- helpers ---------------------------------------------------------------

def _client(args: argparse.Namespace) -> DebugClient:
    return DebugClient(args.host, token=args.token, port=args.port)


def _out_dir() -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    return OUT_DIR


def _run_id_of(rec: dict) -> str | None:
    """Best-effort run id from a captured record: an explicit run_id anywhere in the
    payload tree, else a `run:*` trace."""
    def dig(v):
        if isinstance(v, dict):
            for key in ("run_id", "runId"):
                if v.get(key):
                    return str(v[key])
            for sub in v.values():
                got = dig(sub)
                if got:
                    return got
        return None

    rid = dig(rec.get("payload"))
    if rid:
        return rid
    trace = rec.get("trace")
    return trace if isinstance(trace, str) and trace.startswith("run") else None


def _select_run(records: list[dict], *, run: str | None = None, last: bool = False):
    """Return (subset, label). A run is scoped by its TIME WINDOW — every record between
    its run-started and run-finished — so diag/value frames (which carry no run_id) are
    included, not just the events tagged with the run id."""
    target = run
    if target is None and last:
        starts = [r for r in records if r.get("type") == "run-started"]
        if starts:
            target = _run_id_of(starts[-1])
        else:
            target = next((rid for rid in reversed([_run_id_of(r) for r in records]) if rid), None)
    if target is None:
        return records, "ring"
    t0 = t1 = None
    for r in records:
        rid = _run_id_of(r)
        if r.get("type") == "run-started" and rid == target:
            t0 = r.get("ts")
        elif r.get("type") == "run-finished" and rid == target:
            t1 = r.get("ts")
    if t0 is not None:
        hi = t1 if t1 is not None else max((r.get("ts") or 0 for r in records), default=t0)
        return [r for r in records if r.get("ts") is not None and t0 <= r["ts"] <= hi], target
    return [r for r in records if _run_id_of(r) == target], target   # fallback: tag match


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


# --- commands --------------------------------------------------------------

def cmd_health(args: argparse.Namespace) -> int:
    print(json.dumps(_client(args).health(), indent=2))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    client = _client(args)
    records = client.events(since=args.since, subsystem=args.module, level=args.level,
                            topic=args.topic, text=args.grep, limit=args.limit)
    label = "ring"
    if args.run or args.last_run:
        records, label = _select_run(records, run=args.run, last=args.last_run)
        if not records:
            print("no run found in the current ring", file=sys.stderr)
            return 1
    elif args.since is None:
        label = time.strftime("%Y%m%d-%H%M%S")

    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in label)
    path = _out_dir() / f"{args.host}-{safe}.jsonl"
    _write_jsonl(path, records)
    print(f"pulled {len(records)} records -> {path}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    client = _client(args)

    async def _run() -> None:
        async for rec in client.watch(level=args.level, subsystem=args.module, topic=args.topic):
            if args.grep and args.grep.lower() not in json.dumps(rec).lower():
                continue
            print(json.dumps(rec))

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_level(args: argparse.Namespace) -> int:
    client = _client(args)
    if args.set:
        print(json.dumps(client.set_level(args.module, args.set), indent=2))
    else:
        print(json.dumps(client.levels(), indent=2))
    return 0


def cmd_snapshots(args: argparse.Namespace) -> int:
    client = _client(args)
    if args.get:
        path = _out_dir() / f"{args.host}-snapshot-{args.get}.jsonl"
        path.write_text(client.snapshot(args.get), encoding="utf-8")
        print(f"snapshot -> {path}")
    else:
        print(json.dumps(client.snapshots(), indent=2))
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    from tmf_debug.digest import digest_file
    out = digest_file(Path(args.file))
    print(f"digest -> {out}")
    return 0


def cmd_why(args: argparse.Namespace) -> int:
    """pull the last run + digest it + print the first fault (REMOTE_DEBUG.md §8)."""
    from tmf_debug.digest import digest_file
    client = _client(args)
    records = client.events(limit=args.limit)
    records, label = _select_run(records, run=args.run, last=True)
    if not records:
        print("no run found in the current ring", file=sys.stderr)
        return 1
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in str(label))
    path = _out_dir() / f"{args.host}-{safe}.jsonl"
    _write_jsonl(path, records)
    out = digest_file(path)
    data = json.loads(out.read_text(encoding="utf-8"))
    ff = data.get("first_fault")
    print(json.dumps(ff, indent=2) if ff else "no fault found in this run")
    print(f"\ndigest: {out}\nraw:    {path}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Offline export of a bench's diagnostics into ONE zip, for a PC with no network path to a laptop.

    Runs ON the bench (or against its copied state dir) and reads files directly - no sidecar needed. The
    implementation is the framework's stdlib-only `debug_server.export`; on an installed bench with no
    Python, run `run.exe --debug-export [out.zip]` instead (same code, no tmf-debug install required)."""
    try:
        from debug_server.export import main as export_main
    except ImportError:
        print("tmf-debug export needs the framework's backend/ on PYTHONPATH (run it from a source checkout, "
              "or on an installed bench use:  run.exe --debug-export [out.zip])", file=sys.stderr)
        return 2
    argv = ([args.out] if args.out else []) + (["--state-dir", args.state_dir] if args.state_dir else [])
    return export_main(argv + ["--rows", str(args.rows)])


# --- parser ----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tmf-debug", description="Remote debug client for the TMF Debug Server.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def host_args(sp, *, needs_host=True):
        if needs_host:
            sp.add_argument("--host", required=True, help="bench host/address")
            sp.add_argument("--port", type=int, default=DEFAULT_PORT)
            sp.add_argument("--token", default=None, help="debug bearer token")

    def filters(sp):
        sp.add_argument("--module", default=None, help="subsystem filter")
        sp.add_argument("--level", default=None, help="min level (debug|info|warning|error|critical)")
        sp.add_argument("--topic", default=None, help="subtopic prefix filter")
        sp.add_argument("--grep", default=None, help="free-text filter")

    sp = sub.add_parser("watch", help="live WS tail to stdout")
    host_args(sp)
    filters(sp)
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("pull", help="fetch records to .debug/<host>-<id>.jsonl")
    host_args(sp)
    filters(sp)
    sp.add_argument("--since", type=int, default=None, help="only records after this seq")
    sp.add_argument("--run", default=None, help="only this run id")
    sp.add_argument("--last-run", action="store_true", help="only the most recent run")
    sp.add_argument("--limit", type=int, default=20000)
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("health", help="volume, drops, versions")
    host_args(sp)
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("level", help="live per-subsystem verbosity")
    host_args(sp)
    sp.add_argument("--module", required=True, help="subsystem")
    sp.add_argument("--set", default=None, help="new level; omit to read current")
    sp.set_defaults(func=cmd_level)

    sp = sub.add_parser("snapshots", help="list/download failure snapshots")
    host_args(sp)
    sp.add_argument("--get", default=None, help="snapshot id to download")
    sp.set_defaults(func=cmd_snapshots)

    sp = sub.add_parser("digest", help="condense a .jsonl capture into <file>.digest.json")
    sp.add_argument("file", help="the .jsonl capture to condense")
    sp.set_defaults(func=cmd_digest)

    sp = sub.add_parser("why", help="pull + digest + print the first fault")
    host_args(sp)
    filters(sp)
    sp.add_argument("--last-run", action="store_true", default=True, help=argparse.SUPPRESS)
    sp.add_argument("--run", default=None)
    sp.add_argument("--since", type=int, default=None, help=argparse.SUPPRESS)
    sp.add_argument("--limit", type=int, default=20000)
    sp.set_defaults(func=cmd_why)

    sp = sub.add_parser("export", help="pack a bench's diagnostics (recorder + logs + config) into one zip")
    sp.add_argument("out", nargs="?", default=None, help="output zip")
    sp.add_argument("--state-dir", default=None, help="deploy/state root (default: TMF_STATE_DIR or backend/)")
    sp.add_argument("--rows", type=int, default=5000, help="max log rows per table")
    sp.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

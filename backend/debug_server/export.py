"""Offline diagnostic export - one zip for an air-gapped bench (REMOTE_DEBUG.md, FRAMEWORK CR A2).

The Debug Server's pull API needs a network path from a laptop to the bench. A client PC often has none, so
this packs everything a developer needs into ONE file that can be carried out on a USB stick:

    diagnostics/<name>.jsonl[.gz]   the flight recorder: rolling capture + 30 s failure snapshots  (data/debug/)
    logs/error_log.jsonl            last N error_log rows from the station DB
    logs/action_log.jsonl           last N action_log rows (who did what, with what result)
    logs/launcher.log               the supervisor log (relaunches, update swaps) if present
    config/app.json                 live app config, secrets redacted
    config/controller.generated.json  exactly what the supervised controller was started with
    environment.json                versions, OS, Python, frozen/source, paths, free disk, TMF_* env
    MANIFEST.json                   what was packed, sizes, and what was missing (never silently empty)

Standard library only: it runs inside the frozen `run.exe` (`run.exe --debug-export [out.zip]`) as well as
from source (`python -m debug_server.export`). Read-only on the station state - it never writes there.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

_SECRET_KEYS = ("password", "passwd", "secret", "token", "api_key", "apikey", "credential", "private_key")
_DEFAULT_ROWS = 5000


def _redact(obj):
    """Copy of `obj` with every secret-looking value replaced - config can carry DB / MES credentials."""
    if isinstance(obj, dict):
        return {k: ("***redacted***" if any(s in k.lower() for s in _SECRET_KEYS) and v not in (None, "", False)
                    else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _db_rows(db: Path, record_type: str, limit: int) -> list[dict]:
    # read-only URI: exporting must never take a write lock on (or create) the station DB
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        cur = con.execute("SELECT id, ts, station, source_version, summary, data FROM records "
                          "WHERE type=? ORDER BY ts DESC LIMIT ?", (record_type, limit))
        rows = []
        for rid, ts, station, ver, summary, data in cur:
            try:
                payload = json.loads(data)
            except ValueError:
                payload = {"_unparsed": data}
            rows.append({"id": rid, "ts": ts, "station": station, "source_version": ver,
                         "summary": summary, "data": payload})
        return list(reversed(rows))
    finally:
        con.close()


def _environment(state: Path, bundle: Path | None) -> dict:
    env: dict = {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": platform.platform(), "machine": platform.machine(),
        "python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable, "state_root": str(state), "bundle_root": str(bundle) if bundle else None,
        "tmf_env": {k: v for k, v in os.environ.items() if k.startswith("TMF_")},
    }
    try:
        from core import __version__, app_version
        env["framework_version"], env["app_version"] = __version__, app_version()
    except Exception as exc:  # noqa: BLE001 - an export must work even when the core cannot import
        env["version_error"] = f"{type(exc).__name__}: {exc}"
    try:
        env["disk_free_gb"] = round(shutil.disk_usage(state).free / 2**30, 2)
    except OSError:
        pass
    if bundle and (bundle / "RELEASE.json").is_file():
        try:
            rel = json.loads((bundle / "RELEASE.json").read_text(encoding="utf-8"))
            env["release"] = {k: rel.get(k) for k in ("product", "version", "framework_version", "built_at")}
        except ValueError:
            pass
    return env


def export_bundle(out: Path | str, *, state_root: Path | None = None, rows: int = _DEFAULT_ROWS) -> dict:
    """Write the zip to `out` and return its MANIFEST (also stored inside)."""
    from core.paths import bundle_root, state_root as _state_root
    state = Path(state_root) if state_root else _state_root()
    try:
        bundle = bundle_root()
    except Exception:  # noqa: BLE001
        bundle = None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"files": [], "missing": [], "state_root": str(state), "rows_limit": rows}

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def add_file(src: Path, arc: str) -> None:
            if src.is_file():
                z.write(src, arc)
                manifest["files"].append({"name": arc, "bytes": src.stat().st_size})
            else:
                manifest["missing"].append(f"{arc} ({src} not found)")

        def add_text(arc: str, text: str) -> None:
            z.writestr(arc, text)
            manifest["files"].append({"name": arc, "bytes": len(text.encode("utf-8"))})

        # flight recorder (rolling capture, rotated .gz, snapshots)
        dbg = state / "data" / "debug"
        if dbg.is_dir():
            files = sorted(p for p in dbg.rglob("*") if p.is_file())
            for p in files:
                add_file(p, f"diagnostics/{p.relative_to(dbg).as_posix()}")
            if not files:
                manifest["missing"].append(f"diagnostics/ ({dbg} is empty - was Remote debugging switched on?)")
        else:
            manifest["missing"].append(f"diagnostics/ ({dbg} not found - Remote debugging was never enabled)")

        # station DB log rows
        db = state / "data" / "tmf.sqlite"
        for rtype in ("error_log", "action_log"):
            if db.is_file():
                try:
                    data = _db_rows(db, rtype, rows)
                    add_text(f"logs/{rtype}.jsonl", "".join(json.dumps(r, default=str) + "\n" for r in data))
                except sqlite3.Error as exc:
                    manifest["missing"].append(f"logs/{rtype}.jsonl ({type(exc).__name__}: {exc})")
            else:
                manifest["missing"].append(f"logs/{rtype}.jsonl ({db} not found)")
        add_file(state / "data" / "launcher.log", "logs/launcher.log")

        # config - what the station actually ran with
        app_json = state / "config" / "app.json"
        if app_json.is_file():
            try:
                add_text("config/app.json", json.dumps(_redact(json.loads(app_json.read_text(encoding="utf-8"))),
                                                       indent=2))
            except ValueError as exc:
                manifest["missing"].append(f"config/app.json (unreadable: {exc})")
        else:
            manifest["missing"].append(f"config/app.json ({app_json} not found)")
        gen = state / "data" / "controller.generated.json"
        if gen.is_file():
            try:
                add_text("config/controller.generated.json",
                         json.dumps(_redact(json.loads(gen.read_text(encoding="utf-8"))), indent=2))
            except ValueError:
                add_file(gen, "config/controller.generated.json")
        else:
            manifest["missing"].append(f"config/controller.generated.json ({gen} not found)")

        add_text("environment.json", json.dumps(_environment(state, bundle), indent=2))
        manifest["created"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
    return manifest


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="debug-export", description="Pack the station's diagnostics into one zip.")
    ap.add_argument("out", nargs="?", help="output zip (default: tmf-debug-<host>-<timestamp>.zip in the cwd)")
    ap.add_argument("--state-dir", default=None, help="deploy/state root (default: TMF_STATE_DIR or backend/)")
    ap.add_argument("--rows", type=int, default=_DEFAULT_ROWS, help="max log rows per table")
    args = ap.parse_args(argv)
    out = Path(args.out or f"tmf-debug-{platform.node() or 'station'}-{time.strftime('%Y%m%d-%H%M%S')}.zip")
    m = export_bundle(out, state_root=Path(args.state_dir) if args.state_dir else None, rows=args.rows)
    total = sum(f["bytes"] for f in m["files"])
    print(f"export: {len(m['files'])} file(s), {total / 1024:.0f} KB -> {out.resolve()}")
    for miss in m["missing"]:
        print(f"  missing: {miss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

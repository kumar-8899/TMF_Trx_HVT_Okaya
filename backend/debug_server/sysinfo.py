"""Machine-level facts for the diagnostics bundle (REMOTE_DEBUG.md section 14, export v2).

Everything an engineer used to be asked to run by hand: which processes are running and what holds the app's
ports, which SQL Server ODBC drivers are installed, what the running app answers on /healthz and /readyz, and
whether the installed `run.dist` still matches the hashes it shipped with (a half-applied update).

STANDARD LIBRARY ONLY and strictly READ-ONLY: this runs inside the frozen `run.exe --debug-export` as well as from
the TMF Debug Tool. Every function returns a JSON-able dict and NEVER raises - a probe that cannot run says so
(`note`/`error`) instead of failing the whole export.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PORTS = {8000: "app (backend)", 1883: "MQTT broker", 8001: "in-app Debug Server", 8010: "TMF Debug Tool", 5173: "Vite dev server"}
# Processes worth listing: ours and the things that collide with ours.
_INTERESTING = re.compile(r"(run\.exe|run_station|python|pythonw|mosquitto|tmf-debug-tool|controller|node|uvicorn)", re.I)


def _run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, r.stdout or ""
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def processes() -> dict:
    """Relevant processes with PID and command line."""
    rows: list[dict] = []
    if sys.platform == "win32":
        ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine | "
              "ConvertTo-Json -Compress")
        rc, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=40)
        if rc != 0 or not out.strip():
            return {"error": f"could not list processes: {out.strip()[:200]}", "processes": []}
        try:
            data = json.loads(out)
        except ValueError:
            return {"error": "process list was not valid JSON", "processes": []}
        for p in (data if isinstance(data, list) else [data]):
            name = p.get("Name") or ""
            if _INTERESTING.search(name):
                rows.append({"pid": p.get("ProcessId"), "ppid": p.get("ParentProcessId"), "name": name,
                             "exe": p.get("ExecutablePath"), "cmdline": (p.get("CommandLine") or "")[:400]})
    else:
        rc, out = _run(["ps", "-eo", "pid,ppid,comm,args"])
        for ln in out.splitlines()[1:]:
            parts = ln.split(None, 3)
            if len(parts) >= 3 and _INTERESTING.search(parts[2]):
                rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "name": parts[2], "exe": None,
                             "cmdline": (parts[3] if len(parts) > 3 else "")[:400]})
    return {"processes": rows}


def ports(procs: dict | None = None) -> dict:
    """Who is LISTENING on the ports the app uses (pid + command line when known)."""
    by_pid = {p["pid"]: p for p in (procs or processes()).get("processes", [])}
    found: dict[int, dict] = {}
    if sys.platform == "win32":
        rc, out = _run(["netstat", "-ano", "-p", "TCP"])
        for ln in out.splitlines():
            parts = ln.split()
            if len(parts) >= 5 and parts[3] == "LISTENING":
                m = re.search(r":(\d+)$", parts[1])
                if m and int(m.group(1)) in PORTS:
                    found[int(m.group(1))] = {"pid": int(parts[4])}
    else:
        rc, out = _run(["ss", "-ltnp"])
        for ln in out.splitlines():
            m = re.search(r":(\d+)\s", ln)
            pid = re.search(r"pid=(\d+)", ln)
            if m and int(m.group(1)) in PORTS:
                found[int(m.group(1))] = {"pid": int(pid.group(1)) if pid else None}
    res = {}
    for port, what in PORTS.items():
        e = found.get(port)
        if e is None:
            res[str(port)] = {"role": what, "listening": False}
        else:
            p = by_pid.get(e["pid"], {})
            res[str(port)] = {"role": what, "listening": True, "pid": e["pid"], "name": p.get("name"),
                              "cmdline": p.get("cmdline")}
    return {"ports": res}


def odbc_drivers() -> dict:
    """Installed SQL Server ODBC drivers, newest first (pyodbc when available)."""
    try:
        import pyodbc  # noqa: PLC0415
        names = [d for d in pyodbc.drivers() if "sql server" in d.lower()]
        return {"drivers": names, "all": list(pyodbc.drivers())}
    except Exception as exc:  # noqa: BLE001
        return {"drivers": [], "note": f"pyodbc not usable here ({type(exc).__name__}: {exc}); ODBC drivers not listed"}


def _get(url: str, timeout: float = 2.5) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310 - loopback only (callers pass 127.0.0.1)
            body = r.read(200_000).decode("utf-8", "replace")
            try:
                return {"status": r.status, "body": json.loads(body)}
            except ValueError:
                return {"status": r.status, "body": body[:500]}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def app_health(port: int | None = None) -> dict:
    """What the running app answers on loopback; a note (not an error) when it is not running."""
    port = port or int(os.environ.get("TMF_PORT") or 8000)
    base = f"http://127.0.0.1:{port}"
    out = {"port": port, "healthz": _get(base + "/healthz"), "readyz": _get(base + "/readyz"),
           "modules": _get(base + "/modules/status")}
    out["app_running"] = "status" in out["healthz"]
    if not out["app_running"]:
        out["note"] = "the app did not answer on loopback - it is not running, or is on another port (TMF_PORT)"
    return out


def integrity(bundle_root: Path | None, *, budget_s: float = 90.0) -> dict:
    """Compare every file of the installed build with the sha256 table in RELEASE.json (built by build_release.manifest).

    Keys are relative to the deploy root (`run.dist/...`, `run_station.exe`), i.e. the PARENT of run.dist. A file that
    is missing, differs, or cannot be read is reported; a time budget keeps a slow disk from stalling the export."""
    if bundle_root is None or not (Path(bundle_root) / "RELEASE.json").is_file():
        return {"status": "unavailable", "note": "no RELEASE.json beside this install (a source checkout, or not a built release)"}
    bundle_root = Path(bundle_root)
    try:
        rel = json.loads((bundle_root / "RELEASE.json").read_text(encoding="utf-8"))
    except ValueError as exc:
        return {"status": "unavailable", "note": f"RELEASE.json is not valid JSON: {exc}"}
    table: dict = rel.get("sha256") or {}
    root = bundle_root.parent
    missing, modified, unreadable, checked = [], [], [], 0
    t0 = time.monotonic()
    truncated = False
    for key, want in table.items():
        if time.monotonic() - t0 > budget_s:
            truncated = True
            break
        p = root / key
        if not p.is_file():
            missing.append(key)
            continue
        try:
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        except OSError as exc:
            unreadable.append({"file": key, "error": str(exc)[:120]})
            continue
        checked += 1
        if h.hexdigest() != want:
            modified.append(key)
    ok = not (missing or modified)
    return {"status": "ok" if ok and not truncated else ("incomplete" if truncated and ok else "MISMATCH"),
            "version": rel.get("version"), "framework_version": rel.get("framework_version"),
            "expected_files": len(table), "checked": checked, "missing": missing[:200], "modified": modified[:200],
            "unreadable": unreadable[:50], "truncated": truncated,
            "note": ("every file matches the release it shipped as" if ok and not truncated else
                     "files differ from the shipped release - a half-applied update, antivirus quarantine, or a manual edit")}

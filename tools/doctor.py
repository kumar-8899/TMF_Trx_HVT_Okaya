"""doctor - is THIS machine set up correctly to develop and run this fork? (docs/DEVELOPER_ONBOARDING.md)

    python tools/doctor.py                 # human-readable report, exit 1 if any check is an error
    python tools/doctor.py --json          # machine-readable (skills call this)
    python tools/doctor.py --fix           # also perform the SAFE, reversible fixes and print each one

Every check yields {id, ok, severity, detail, fix}; severity is "error" | "warning" | "info". `--fix` only does
things that are safe to repeat: create `.venv`, re-run the editable installs into the active interpreter, copy a
missing live config from its `*.example.json`, `npm install` in `frontend/`, and `config_doctor --apply` (additive).
It never kills a process and never edits a global environment variable - it prints the command instead.

Stdlib only, no repo imports, so it runs before anything is installed. Every side effect goes through `Ctx`, so the
tests drive it with fakes (`backend/tests/test_doctor.py`).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
PORTS = {8000: "the app (backend)", 1883: "the MQTT broker", 8001: "the in-app Debug Server",
         8010: "the TMF Debug Tool", 5173: "the Vite dev server"}
EDITABLE = ("core", "controller", "instrumentlib", "tmf_debug")      # debug_tool runs as `python -m debug_tool` (no package to install)
MOSQUITTO_FALLBACKS = (r"D:\tools\mosquitto\mosquitto.exe", r"C:\Program Files\mosquitto\mosquitto.exe",
                       r"C:\Program Files (x86)\mosquitto\mosquitto.exe")


@dataclass
class Check:
    id: str
    ok: bool
    severity: str            # error | warning | info
    detail: str
    fix: str = ""            # the command / action that resolves it ("" = nothing to do)
    fixable: bool = False    # True when `--fix` can do it safely itself

    def as_dict(self) -> dict:
        return {"id": self.id, "ok": self.ok, "severity": self.severity, "detail": self.detail,
                "fix": self.fix, "fixable": self.fixable}


def _port_owner_default(port: int) -> dict | None:
    """-> None when nothing listens on `port`, else {pid, cmdline} (best effort; cmdline may be '')."""
    s = socket.socket()
    s.settimeout(0.5)
    try:
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return None
    finally:
        s.close()
    pid, cmd = None, ""
    if sys.platform == "win32":
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                    pid = int(parts[4])
                    break
            if pid:
                ps = (f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine")
                cmd = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                                     text=True, timeout=15).stdout.strip()
        except Exception:  # noqa: BLE001 - diagnostics must never crash the doctor
            pass
    return {"pid": pid, "cmdline": cmd}


def _run_default(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def _find_spec_origin(name: str) -> str | None:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    if spec.origin and spec.origin not in ("built-in", "frozen"):
        return spec.origin
    locs = list(spec.submodule_search_locations or [])
    return locs[0] if locs else None


@dataclass
class Ctx:
    """Everything the checks touch outside pure computation - replaceable in tests."""
    repo: Path = REPO
    env: dict = field(default_factory=lambda: dict(os.environ))
    version_info: tuple = field(default_factory=lambda: tuple(sys.version_info[:3]))
    prefix: str = field(default_factory=lambda: sys.prefix)
    base_prefix: str = field(default_factory=lambda: sys.base_prefix)
    executable: str = field(default_factory=lambda: sys.executable)
    platform: str = field(default_factory=lambda: sys.platform)
    port_owner: Callable[[int], dict | None] = _port_owner_default
    find_origin: Callable[[str], str | None] = _find_spec_origin
    which: Callable[[str], str | None] = shutil.which
    run: Callable[..., tuple[int, str]] = _run_default
    http_ok: Callable[[str], bool] | None = None


def _under(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _apps(ctx: Ctx) -> list[str]:
    base = ctx.repo / "app"
    return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


def _is_fork(ctx: Ctx) -> bool:
    return any((ctx.repo / "app" / a / "VERSION").is_file() for a in _apps(ctx))


# ------------------------------------------------------------------------------------------------ checks

def check_python(ctx: Ctx) -> Check:
    v = ctx.version_info
    ok = tuple(v[:2]) >= (3, 11)
    return Check("python_version", ok, "error", f"Python {'.'.join(map(str, v))}" + ("" if ok else " - 3.11 or newer is required"),
                 "" if ok else "install Python 3.11+ from python.org")


def check_venv(ctx: Ctx) -> Check:
    venv = ctx.repo / ".venv"
    in_venv = ctx.prefix != ctx.base_prefix
    if in_venv and _under(ctx.prefix, ctx.repo):
        return Check("venv", True, "info", f"running in this repo's virtualenv ({ctx.prefix})")
    if venv.is_dir() and not (in_venv and _under(ctx.prefix, ctx.repo)):
        act = r".venv\Scripts\Activate.ps1" if ctx.platform == "win32" else "source .venv/bin/activate"
        return Check("venv", False, "warning", f"{venv} exists but this interpreter ({ctx.executable}) is not it",
                     f"activate it: {act}")
    where = f"another environment ({ctx.prefix})" if in_venv else "the global interpreter"
    return Check("venv", False, "warning",
                 f"no .venv in this repo and you are on {where}: several forks on one PC overwrite each other's "
                 "editable installs", "python -m venv .venv  (then activate it and re-run doctor --fix)", fixable=True)


def check_editable(ctx: Ctx) -> Check:
    bad, missing = [], []
    for name in EDITABLE:
        dir_name = {"core": "backend/core", "instrumentlib": "backend/instrumentlib", "controller": "controller/controller",
                    "tmf_debug": "tmf_debug"}[name]
        if not (ctx.repo / dir_name).is_dir():
            continue                                            # this checkout does not carry it (yet)
        origin = ctx.find_origin(name)
        if origin is None:
            missing.append(name)
        elif not _under(origin, ctx.repo):
            bad.append(f"{name} -> {origin}")
    if bad:
        return Check("editable_installs", False, "error",
                     "these packages import from ANOTHER checkout: " + "; ".join(bad) +
                     " (a test run would silently use that fork's code)",
                     "re-run the editable installs in this repo: python tools/doctor.py --fix", fixable=True)
    if missing:
        return Check("editable_installs", False, "warning", "not installed: " + ", ".join(missing),
                     "python tools/doctor.py --fix", fixable=True)
    return Check("editable_installs", True, "info", "editable installs resolve under this repo")


def check_extras(ctx: Ctx) -> Check:
    want = {"dev": ("pytest", "httpx"), "report-db": ("pymysql", "pyodbc")}
    miss = {k: [m for m in mods if ctx.find_origin(m) is None] for k, mods in want.items()}
    miss = {k: v for k, v in miss.items() if v}
    if not miss:
        return Check("extras", True, "info", "dev and report-db extras are installed")
    return Check("extras", False, "warning", "missing: " + "; ".join(f"{', '.join(v)} (extra '{k}')" for k, v in miss.items()),
                 "cd backend && pip install -e \".[dev,report-db]\"", fixable=True)


def check_node(ctx: Ctx) -> Check:
    fe = ctx.repo / "frontend"
    if not fe.is_dir():
        return Check("frontend_deps", True, "info", "no frontend/ in this checkout")
    node = ctx.which("node")
    if not node:
        return Check("frontend_deps", False, "warning", "Node.js not found on PATH", "install Node 20+ from nodejs.org")
    if not (fe / "node_modules").is_dir():
        return Check("frontend_deps", False, "warning", "frontend/node_modules is missing (station.py's UI build fails with "
                     "'tsc is not recognized')", "cd frontend && npm install", fixable=True)
    return Check("frontend_deps", True, "info", "Node found and frontend/node_modules present")


def check_mosquitto(ctx: Ctx) -> Check:
    cands = [ctx.repo / "deploy" / "vendor" / "mosquitto" / "win64" / "mosquitto.exe", *map(Path, MOSQUITTO_FALLBACKS)]
    found = next((str(c) for c in cands if c.is_file()), None) or ctx.which("mosquitto")
    if found:
        return Check("mosquitto", True, "info", f"broker: {found}")
    return Check("mosquitto", False, "warning", "no Mosquitto found - the app runs but MQTT features stay offline",
                 "powershell deploy/fetch-mosquitto.ps1  (vendors it) or install Mosquitto")


def check_ports(ctx: Ctx) -> list[Check]:
    out = []
    for port, what in PORTS.items():
        owner = ctx.port_owner(port)
        if owner is None:
            out.append(Check(f"port_{port}", True, "info", f":{port} free ({what})"))
            continue
        cmd, pid = owner.get("cmdline") or "", owner.get("pid")
        norm = lambda t: t.lower().replace("/", "\\")          # noqa: E731
        ours = bool(cmd) and norm(str(ctx.repo)) in norm(cmd)
        who = f"pid {pid}" + (f" - {cmd[:140]}" if cmd else " (command line unknown)")
        if port == 1883 and (not cmd or "mosquitto" in cmd.lower()):
            # One broker per PC is shared by design (a vendored or installed Mosquitto); not a stray.
            out.append(Check(f"port_{port}", True, "info", f":{port} is in use - a broker is listening ({who})"))
        elif ours:
            out.append(Check(f"port_{port}", True, "info", f":{port} is held by THIS repo's process ({who})"))
        else:
            out.append(Check(f"port_{port}", False, "warning",
                             f":{port} ({what}) is held by a process that is not from this repo: {who}. A stray process "
                             "looks like your app - check before trusting a health check",
                             f"stop that one process by PID (never by name): taskkill /PID {pid} /T" if pid else "find and stop it by PID"))
    return out


def check_env_vars(ctx: Ctx) -> list[Check]:
    out = []
    fr = ctx.env.get("FRAMEWORK_REMOTE")
    out.append(Check("env_FRAMEWORK_REMOTE", bool(fr), "warning" if not fr else "info",
                     f"FRAMEWORK_REMOTE={fr}" if fr else "FRAMEWORK_REMOTE is not set (the skills use it to find the framework)",
                     "" if fr else 'setx FRAMEWORK_REMOTE "https://github.com/<owner>/Super_Test_App.git"  (then reopen the terminal)'))
    lib = ctx.env.get("TMF_INSTRUMENT_LIBRARY")
    if not lib:
        out.append(Check("env_TMF_INSTRUMENT_LIBRARY", False, "warning",
                         "TMF_INSTRUMENT_LIBRARY is not set (the skills copy drivers from there)",
                         'setx TMF_INSTRUMENT_LIBRARY "C:\\dev\\Instrument_Library"  (then reopen the terminal)'))
    elif not Path(lib).is_dir():
        out.append(Check("env_TMF_INSTRUMENT_LIBRARY", False, "error", f"TMF_INSTRUMENT_LIBRARY points at a missing folder: {lib}",
                         "fix the path (setx TMF_INSTRUMENT_LIBRARY ...)"))
    else:
        out.append(Check("env_TMF_INSTRUMENT_LIBRARY", True, "info", f"TMF_INSTRUMENT_LIBRARY={lib}"))
    return out


def check_config(ctx: Ctx) -> list[Check]:
    cfg = ctx.repo / "backend" / "config"
    if not cfg.is_dir():
        return []
    out = []
    missing = [n for n in ("app", "license") if (cfg / f"{n}.example.json").is_file() and not (cfg / f"{n}.json").is_file()]
    if missing:
        out.append(Check("live_config", False, "warning", "live config missing: " + ", ".join(f"{m}.json" for m in missing)
                         + " (gitignored; copied from the *.example.json)",
                         "python tools/doctor.py --fix  (copies the examples)", fixable=True))
        return out
    out.append(Check("live_config", True, "info", "live app.json / license.json present"))
    rc, text = ctx.run([ctx.executable, "-m", "tools.config_doctor"], cwd=ctx.repo / "backend", timeout=60)
    if rc == 0 and "up to date" in text:
        out.append(Check("config_drift", True, "info", "live config matches the examples"))
    elif rc == 0 and "addition(s)" in text:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("+")]
        out.append(Check("config_drift", False, "warning",
                         f"{len(lines)} addition(s) from newer examples are missing from your live config "
                         "(new permissions/modules; without them you see 403s): " + "; ".join(lines[:4]),
                         "python -m tools.config_doctor --apply  (in backend/), then restart and re-login", fixable=True))
    else:
        out.append(Check("config_drift", False, "info", f"could not run config_doctor (exit {rc}): {text.strip()[:140]}"))
    return out


def check_git(ctx: Ctx) -> list[Check]:
    if not (ctx.repo / ".git").exists():
        return []
    out = []
    rc, remotes = ctx.run(["git", "remote", "-v"], cwd=ctx.repo, timeout=20)
    has_up = bool(re.search(r"^upstream\s", remotes, re.M))
    if _is_fork(ctx):
        if not has_up:
            out.append(Check("git_upstream", False, "warning", "no `upstream` remote - this fork cannot pull framework releases",
                             "git remote add upstream <framework url> ; git remote set-url --push upstream DISABLE"))
        else:
            push = re.search(r"^upstream\s+(\S+)\s+\(push\)", remotes, re.M)
            if push and push.group(1).upper() != "DISABLE":
                out.append(Check("git_upstream", False, "warning",
                                 f"`upstream` is push-enabled ({push.group(1)}) - an app commit could reach the framework repo",
                                 "git remote set-url --push upstream DISABLE"))
            else:
                out.append(Check("git_upstream", True, "info", "`upstream` remote present and push-disabled"))
        rc, tag = ctx.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*"], cwd=ctx.repo, timeout=20)
        out.append(Check("framework_base_tag", rc == 0, "info" if rc == 0 else "warning",
                         f"base framework tag: {tag.strip()}" if rc == 0 else "no framework `v*` tag is an ancestor of HEAD",
                         "" if rc == 0 else "git fetch upstream --tags"))
    return out


def check_line_endings(ctx: Ctx) -> Check | None:
    if not (ctx.repo / ".git").exists():
        return None
    if not (ctx.repo / ".gitattributes").is_file():
        return Check("gitattributes", False, "warning",
                     ".gitattributes is missing - a scripted edit on Windows can flip LF files to CRLF (whole-file diffs, merge conflicts)",
                     "merge framework v1.32.0 or newer (it ships .gitattributes)")
    rc, text = ctx.run(["git", "ls-files", "--eol"], cwd=ctx.repo, timeout=60)
    if rc != 0:
        return Check("gitattributes", True, "info", ".gitattributes present")
    drift = [ln.split("\t", 1)[1] for ln in text.splitlines() if ln.startswith("i/lf") and "w/crlf" in ln.split("\t")[0]]
    if drift:
        return Check("line_endings", False, "warning",
                     f"{len(drift)} tracked LF file(s) are CRLF in your working copy (e.g. {', '.join(drift[:3])}) - something rewrote them",
                     "re-checkout them: git checkout -- <file>  (or git add --renormalize <file>)")
    return Check("line_endings", True, "info", ".gitattributes present; no tracked LF file has drifted to CRLF")


def check_odbc(ctx: Ctx) -> Check | None:
    if ctx.platform != "win32":
        return None
    try:
        import pyodbc  # noqa: PLC0415
        names = [d for d in pyodbc.drivers() if "sql server" in d.lower()]
    except Exception:  # noqa: BLE001
        return Check("odbc_drivers", True, "info", "pyodbc not usable here - SQL Server ODBC drivers not checked")
    return Check("odbc_drivers", bool(names), "info", ("SQL Server ODBC drivers: " + ", ".join(names)) if names else
                 "no SQL Server ODBC driver installed (only needed if a report/MES database is SQL Server)")


def _delivery():
    spec = importlib.util.spec_from_file_location("debug_tool_delivery", Path(__file__).resolve().parent / "debug_tool_delivery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_debug_tool(ctx: Ctx) -> list[Check]:
    out = []
    dd = _delivery()
    for slug in _apps(ctx):
        f = ctx.repo / "app" / slug / "debug-tool.json"
        if not f.is_file():
            continue
        try:
            cfg = dd.load_config(slug, ctx.repo)
        except dd.DeliveryError as exc:
            out.append(Check(f"debug_tool_json_{slug}", False, "error", f"app/{slug}/debug-tool.json is not valid JSON: {exc}"))
            continue
        problems = dd.validate(cfg)                                     # the shipped deploy/debug-tool.schema.json
        out.append(Check(f"debug_tool_json_{slug}", not problems, "error" if problems else "info",
                         f"app/{slug}/debug-tool.json: delivery={cfg.get('delivery')!r}, version={cfg.get('version')!r}" if not problems
                         else f"app/{slug}/debug-tool.json: " + "; ".join(problems)))
        if not problems and cfg.get("delivery") == "bundle" and dd.find_zip(cfg["version"], ctx.repo) is None:
            out.append(Check(f"debug_tool_zip_{slug}", False, "warning",
                             f"delivery=bundle pins Debug Tool {cfg['version']} but no tmf-debug-tool-*.zip is cached - cut-release.ps1 will stop at step 7b",
                             f"python tools/debug_tool_delivery.py fetch --slug {slug}"))
    mcp = ctx.repo / ".mcp.json"
    if mcp.is_file() and ctx.http_ok is not None:
        try:
            servers = json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers", {})
        except ValueError:
            servers = {}
        for name, spec in servers.items():
            url = spec.get("url") if isinstance(spec, dict) else None
            if url:
                ok = ctx.http_ok(url.rsplit("/mcp", 1)[0] + "/debug/health")
                out.append(Check(f"bench_{name}", ok, "info", f"bench '{name}' ({url}) " + ("reachable" if ok else "not reachable right now")))
    return out


def run_checks(ctx: Ctx | None = None) -> list[Check]:
    ctx = ctx or Ctx()
    checks: list[Check] = [check_python(ctx), check_venv(ctx), check_editable(ctx), check_extras(ctx), check_node(ctx),
                           check_mosquitto(ctx)]
    checks += check_ports(ctx)
    checks += check_env_vars(ctx)
    checks += check_config(ctx)
    checks += check_git(ctx)
    for extra in (check_line_endings(ctx), check_odbc(ctx)):
        if extra:
            checks.append(extra)
    checks += check_debug_tool(ctx)
    return checks


# ------------------------------------------------------------------------------------------------ --fix

def apply_fixes(checks: list[Check], ctx: Ctx, say: Callable[[str], None] = print) -> list[str]:
    """Run the safe fixes for the failed, fixable checks. Returns what was done (also printed)."""
    failed = {c.id for c in checks if not c.ok and c.fixable}
    done: list[str] = []
    py = ctx.executable
    repo = ctx.repo

    def step(title: str, cmd: list[str], cwd: Path | None = None) -> bool:
        say(f"  -> {title}: {' '.join(cmd)}")
        rc, out = ctx.run(cmd, cwd=cwd or repo, timeout=900)
        done.append(f"{title}: {'ok' if rc == 0 else f'FAILED (exit {rc}) {out.strip()[-200:]}'}")
        return rc == 0

    if "venv" in failed and not (repo / ".venv").is_dir():
        if step("create .venv", [py, "-m", "venv", ".venv"]):
            act = r".venv\Scripts\Activate.ps1" if ctx.platform == "win32" else "source .venv/bin/activate"
            say(f"     activate it ({act}) and re-run `python tools/doctor.py --fix` so the installs go into it")
            return done                      # the remaining installs belong in the NEW environment
    if "live_config" in failed:
        for n in ("app", "license"):
            ex, live = repo / "backend" / "config" / f"{n}.example.json", repo / "backend" / "config" / f"{n}.json"
            if ex.is_file() and not live.is_file():
                shutil.copyfile(ex, live)
                say(f"  -> copied {ex.name} -> {live.name}")
                done.append(f"copied {ex.name} -> {live.name}")
    if failed & {"editable_installs", "extras"} and ctx.prefix == ctx.base_prefix:
        # Re-pointing the GLOBAL interpreter's editable installs is the very thing that breaks the user's other forks.
        say("  -> refusing to run the editable installs into the GLOBAL interpreter (it would re-point every other fork on this PC).")
        say("     create/activate this repo's .venv first, then re-run `python tools/doctor.py --fix`")
        done.append("editable installs skipped: not inside a virtualenv")
    elif failed & {"editable_installs", "extras"}:
        for target, cwd in (("backend/instrumentlib", None), ("backend[dev,report-db]", None), ("controller", None), ("tmf_debug", None)):
            path = repo / target.split("[")[0]
            if path.is_dir():
                spec = f"./{target}" if "[" not in target else f"./{target}"
                step(f"editable install {target}", [py, "-m", "pip", "install", "-e", spec], cwd)
    if "frontend_deps" in failed:
        npm = ctx.which("npm") or "npm"
        step("npm install", [npm, "install"], repo / "frontend")
    if "config_drift" in failed:
        step("config_doctor --apply", [py, "-m", "tools.config_doctor", "--apply"], repo / "backend")
        say("     restart the app and log in again (permissions resolve at login)")
    if not done:
        say("  (nothing safe to fix automatically)")
    return done


# ------------------------------------------------------------------------------------------------ CLI

def render(checks: list[Check]) -> str:
    icon = {"error": "FAIL", "warning": "warn", "info": " ok "}
    lines = []
    for c in checks:
        mark = icon["info"] if c.ok else icon[c.severity]
        lines.append(f"[{mark}] {c.id}: {c.detail}")
        if not c.ok and c.fix:
            lines.append(f"        fix: {c.fix}" + ("   (doctor --fix can do this)" if c.fixable else ""))
    errs = sum(1 for c in checks if not c.ok and c.severity == "error")
    warns = sum(1 for c in checks if not c.ok and c.severity == "warning")
    lines.append(f"\n{len(checks)} checks: {errs} error(s), {warns} warning(s)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="doctor", description="Check this machine/fork is set up correctly.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--fix", action="store_true", help="perform the safe, reversible fixes")
    ap.add_argument("--repo", default=str(REPO), help="repo root to check (default: this one)")
    args = ap.parse_args(argv)
    ctx = Ctx(repo=Path(args.repo))
    checks = run_checks(ctx)
    if args.fix:
        apply_fixes(checks, ctx, say=(lambda s: print(s, file=sys.stderr)) if args.json else print)
        checks = run_checks(ctx)                       # report the state AFTER the fixes
    if args.json:
        print(json.dumps({"ok": not any(not c.ok and c.severity == "error" for c in checks),
                          "checks": [c.as_dict() for c in checks]}, indent=2))
    else:
        print(render(checks))
    return 1 if any(not c.ok and c.severity == "error" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Find the app this tool is debugging and read what it needs from it (read-only).

The tool is installed BESIDE the app (e.g. `<deploy>/tools/debug-tool/`), not inside it, so it cannot count parent
folders. It discovers the install in this order and says how it found it (`source`):

  1. an explicit --state-dir / TMF_STATE_DIR
  2. a running app process: a `run.exe` whose folder holds `RELEASE.json` -> the deploy root is its parent
  3. a folder next to / above the tool that looks like a deploy root (`run.dist/` or `data/tmf.sqlite`)
  4. a source checkout (`backend/config/app.json` + `backend/data`)

Documented contract with the app (a version skew degrades to fewer features, never to wrong data):
  <state_root>/config/app.json        live config (debug block: bind/token/broker; stations; controller kind)
  <state_root>/data/tmf.sqlite        station DB (records table: error_log / action_log)         read-only
  <state_root>/data/launcher.log      supervisor log                                                read-only
  <state_root>/data/debug/            the in-app flight recorder's files                           read-only
  <deploy>/run.dist/RELEASE.json      version + file hashes
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class AppInfo:
    state_root: Path | None
    bundle_root: Path | None                 # run.dist (frozen install) or the repo root (source)
    source: str                              # how it was found
    app_version: str | None = None
    framework_version: str | None = None
    product: str | None = None
    kind: str = "unknown"                    # "installed" | "source" | "unknown"
    app_config: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.state_root is not None

    @property
    def debug_dir(self) -> Path | None:
        return self.state_root / "data" / "debug" if self.state_root else None

    @property
    def db_path(self) -> Path | None:
        return self.state_root / "data" / "tmf.sqlite" if self.state_root else None

    @property
    def launcher_log(self) -> Path | None:
        return self.state_root / "data" / "launcher.log" if self.state_root else None

    def stations(self) -> list[str]:
        st = self.app_config.get("stations")
        if isinstance(st, list) and st:
            return [s if isinstance(s, str) else str(s.get("id") or s.get("station") or "") for s in st if s]
        return ["st1"]

    def debug_block(self) -> dict:
        d = self.app_config.get("debug")
        return d if isinstance(d, dict) else {}

    def broker(self) -> tuple[str, int]:
        d = self.debug_block()
        return str(d.get("broker_host") or "127.0.0.1"), int(d.get("broker_port") or 1883)

    def core_url(self) -> str:
        d = self.debug_block()
        return str(d.get("core_url") or f"http://127.0.0.1:{os.environ.get('TMF_PORT') or 8000}")

    def in_app_recorder_port(self) -> int:
        return int(self.debug_block().get("port") or 8001)

    def in_app_recorder_enabled(self) -> bool:
        return bool(self.debug_block().get("enabled"))

    def as_dict(self) -> dict:
        return {"found": self.found, "state_root": str(self.state_root) if self.state_root else None,
                "bundle_root": str(self.bundle_root) if self.bundle_root else None, "source": self.source,
                "kind": self.kind, "app_version": self.app_version, "framework_version": self.framework_version,
                "product": self.product, "stations": self.stations(), "notes": self.notes}


def _read_json(p: Path) -> dict:
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _looks_like_deploy_root(p: Path) -> bool:
    return (p / "run.dist").is_dir() or (p / "data" / "tmf.sqlite").is_file() or (p / "config" / "app.json").is_file()


def _from_state(state: Path, source: str, bundle: Path | None = None) -> AppInfo:
    dist = bundle if bundle is not None else (state / "run.dist")
    kind = "installed" if (dist / "RELEASE.json").is_file() or (state / "run.dist").is_dir() else "source"
    rel = _read_json(dist / "RELEASE.json") if (dist / "RELEASE.json").is_file() else {}
    info = AppInfo(state_root=state, bundle_root=dist if dist.exists() else None, source=source, kind=kind,
                   app_version=rel.get("version"), framework_version=rel.get("framework_version"), product=rel.get("product"))
    info.app_config = _read_json(state / "config" / "app.json")
    if not info.app_config:
        info.notes.append(f"{state / 'config' / 'app.json'} not found or unreadable - using defaults (broker :1883, station st1)")
    if kind == "source":                             # source checkouts have no RELEASE.json; read the framework version
        try:
            m = re.search(r'^__version__\s*=\s*"([^"]+)"', (state.parent / "backend" / "core" / "__init__.py").read_text(encoding="utf-8"), re.M) \
                or re.search(r'^__version__\s*=\s*"([^"]+)"', (state / "core" / "__init__.py").read_text(encoding="utf-8"), re.M)
            info.framework_version = info.framework_version or (m.group(1) if m else None)
        except OSError:
            pass
    return info


def discover(hint: str | Path | None = None, *, tool_dir: Path | None = None,
             processes: Callable[[], list[dict]] | None = None) -> AppInfo:
    """Locate the app. `processes()` -> [{exe, cmdline}] (injectable; defaults to debug_server.sysinfo)."""
    h = hint or os.environ.get("TMF_STATE_DIR")
    if h:
        p = Path(h)
        return _from_state(p, "explicit --state-dir / TMF_STATE_DIR") if p.is_dir() else \
            AppInfo(None, None, f"explicit path {p} does not exist", notes=[f"{p} is not a directory"])

    if processes is None:
        try:
            from debug_server import sysinfo
            processes = lambda: sysinfo.processes().get("processes", [])      # noqa: E731
        except Exception:                                                    # noqa: BLE001
            processes = lambda: []                                           # noqa: E731
    try:
        for pr in processes():
            exe = pr.get("exe")
            if exe and Path(exe).name.lower() == "run.exe" and (Path(exe).parent / "RELEASE.json").is_file():
                dist = Path(exe).parent
                return _from_state(dist.parent, f"running app process (pid {pr.get('pid')})", dist)
    except Exception:                                                        # noqa: BLE001
        pass

    start = Path(tool_dir) if tool_dir else Path.cwd()
    for cand in [start, *list(start.parents)[:3]]:
        if _looks_like_deploy_root(cand):
            return _from_state(cand, f"deploy root next to the tool ({cand})")
        if (cand / "backend" / "config").is_dir() and (cand / "backend" / "core").is_dir():
            return _from_state(cand / "backend", f"source checkout ({cand})", cand)
    return AppInfo(None, None, "not found", notes=["no app install found - pass --state-dir <deploy root>"])

"""Python-controller supervisor (PYTHON_CONTROLLER.md; MULTI_STATION.md).

When `app.json` selects `controller.kind == "python"`, the app owns the controller's
lifecycle: it generates a controller config from the app's own stations + broker, spawns
`python -m controller` as a child on startup, pumps its stdout into diagnostics, and
terminates it on shutdown. Because this lives in the backend lifespan, EVERY entry point —
`dev.ps1`, the launcher, a frozen build — gets the controller started with the app, with no
per-launcher wiring. `controller.kind == "labview"` (the default) starts nothing: the
LabVIEW engine runs externally exactly as before.

Not started in a frozen build unless a bundled `controller` executable is found beside the
app — source/dev runs use the current interpreter's `-m controller`."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading
from pathlib import Path


class ControllerSupervisor:
    def __init__(self, *, stations: list[str], broker_host: str, broker_port: int,
                 diag, data_dir: Path, repo_root: Path,
                 config_file: str | None = None,
                 instruments: list[dict] | None = None) -> None:
        self._stations = list(stations)
        self._host = broker_host
        self._port = broker_port
        self._diag = diag
        self._data_dir = Path(data_dir)
        self._repo_root = Path(repo_root)
        self._config_file = config_file           # app controller config (map/steps/libraries)
        # The Instruments page is the single source of instrument instances (owner=python,
        # enabled). None ≠ [] only in intent: both mean the controller gets NO instruments
        # until they are configured in the app — even in simulation.
        self._instruments = list(instruments or [])
        self._proc: subprocess.Popen | None = None
        self._pump: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        cmd, cwd = self._command()
        if cmd is None:
            return                                          # already logged why
        cfg_path = self._write_config()
        # A new process group (Windows) lets us deliver CTRL_BREAK for a GRACEFUL stop, so
        # the controller runs its own teardown (safe_state on every instrument) on app exit.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        try:
            self._proc = subprocess.Popen(
                [*cmd, str(cfg_path)], cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=flags)
        except Exception as exc:  # noqa: BLE001 — a controller that won't spawn must not kill the app
            self._diag.warning("controller", "python controller failed to start", error=str(exc))
            return
        self._diag.info("controller", "python controller started",
                        pid=self._proc.pid, stations=self._stations,
                        instruments=len(self._instruments))
        self._pump = threading.Thread(target=self._pump_logs, name="controller-logs", daemon=True)
        self._pump.start()

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        # Graceful first — CTRL_BREAK (Windows) / SIGTERM (POSIX) so the controller unwinds
        # its run threads and drives every instrument to safe state before it dies.
        try:
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        except Exception:  # noqa: BLE001 — fall through to a hard kill
            pass
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._diag.info("controller", "python controller stopped")

    # -- internals ----------------------------------------------------------

    def _command(self) -> tuple[list[str] | None, Path | None]:
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable).resolve().parent / ("controller.exe" if sys.platform == "win32" else "controller")
            if exe.exists():
                return [str(exe)], exe.parent
            self._diag.warning("controller", "controller.kind=python but no bundled controller "
                               "executable found beside the app — not started")
            return None, None
        pkg_dir = self._repo_root / "controller"           # sibling of backend/ in the repo
        if not (pkg_dir / "controller" / "__main__.py").exists():
            self._diag.warning("controller", "controller.kind=python but the controller package "
                               f"was not found at {pkg_dir} — not started")
            return None, None
        return [sys.executable, "-m", "controller"], pkg_dir

    def _write_config(self) -> Path:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        cfg: dict = {}
        # Start from the app's controller config (instruments, variable maps, step-type
        # packages) when given; the app owns broker + simulation + the station list.
        if self._config_file:
            src = Path(self._config_file)
            try:
                cfg = json.loads(src.read_text(encoding="utf-8"))
                cfg_dir = src.resolve().parent
                for st in cfg.get("stations", []):        # resolve variable_map vs the file's dir
                    vm = st.get("variable_map")
                    if vm and not Path(vm).is_absolute():
                        st["variable_map"] = str((cfg_dir / vm).resolve())
            except Exception as exc:  # noqa: BLE001 — bad app config must not crash the app
                self._diag.warning("controller", f"controller config_file unusable: {exc}")
                cfg = {}
        cfg["schema_version"] = 1
        cfg["broker"] = {"host": self._host, "port": self._port}
        # Simulation is controlled ONLY per-instrument, on the Instruments page (its
        # `simulated` toggle). The controller's global `simulation` flag (which forces
        # EVERY instrument simulated, §12.1) is a standalone/dev knob — under app
        # supervision it is always off so the page's per-instrument choice decides.
        cfg["simulation"] = False
        # Instruments come ONLY from the app's Instruments page (config module records) —
        # a controller.json `instruments` list is ignored, so nothing is reachable (even in
        # simulation) until it is configured in the app.
        declared = cfg.pop("instruments", None)
        if declared:
            self._diag.warning("controller", "controller config_file `instruments` ignored — "
                               "instruments are configured on the Instruments page",
                               declared=len(declared), configured=len(self._instruments))
        cfg["instruments"] = self._instruments
        if not self._instruments:
            self._diag.warning("controller", "no instruments configured — the controller starts "
                               "with none; add them on the Instruments page and restart")
        if not cfg.get("stations"):                        # file listed none → use the app's
            cfg["stations"] = [{"station": s} for s in self._stations]
        path = self._data_dir / "controller.generated.json"
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return path

    def _pump_logs(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._diag.info("controller", line)
        except Exception:  # noqa: BLE001 — the pump dies with the process; never propagate
            pass

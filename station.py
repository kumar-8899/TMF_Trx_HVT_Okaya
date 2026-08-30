"""One-click station launcher — broker + backend + desktop window, one process to run.

This is the operator/app entry point that replaces the three-window `dev.ps1` dance
for a shipped station: it starts the local MQTT broker (if it isn't already up),
supervises the backend through `backend/launcher.py` (so the "Relaunch to apply" and
signed-update loop keep working), waits for the edge to come up, and opens the UI in a
native **pywebview** window pointing at http://127.0.0.1:8000 — where the backend now
serves the built SPA on one origin (core/services/spa.py).

    python station.py                 # production feel: backend serves the built UI, native window
    python station.py --dev           # development: Vite + HMR on :5173, window points there
    python station.py --browser       # open the default browser instead of a native window
    python station.py --fullscreen    # kiosk-style window (also --frameless)
    python station.py --no-window     # run the services only (headless), no window

Shutdown is graceful. Closing the window (or the UI's "Shut down station" button) sends
the backend a console CTRL_BREAK so its lifespan teardown runs — modules stop and the
Python controller drives every instrument to a safe state — before the broker is stopped.
Only what this launcher started is stopped; an already-running broker is left alone.

pywebview is optional (`pip install -e "backend[desktop]"`). Without it, the launcher
falls back to the default browser and says so.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
IS_WIN = sys.platform == "win32"

BACKEND_PORT = 8000
VITE_PORT = 5173
BROKER_PORT = 1883
HEALTH_URL = f"http://127.0.0.1:{BACKEND_PORT}/healthz"


# --------------------------------------------------------------------------- utils
def _log(msg: str) -> None:
    print(f"station: {msg}", flush=True)


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    """True if the edge answered at all — a 404 (e.g. GET / without an html Accept,
    which the SPA middleware only serves to browser navigations) still means up."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True  # server responded (4xx) -> the edge is listening
    except OSError:
        return False


def _frontend_stale(dist_index: Path) -> bool:
    """True if the built bundle is older than the frontend source (a source checkout
    where someone edited the UI but didn't rebuild). A frozen release has no
    frontend/src, so its baked bundle is always trusted (returns False)."""
    src = FRONTEND / "src"
    if not src.is_dir() or not dist_index.is_file():
        return False
    built = dist_index.stat().st_mtime
    watch = [FRONTEND / "package.json", FRONTEND / "index.html", FRONTEND / "vite.config.ts"]
    for p in list(src.rglob("*")) + watch:
        try:
            if p.is_file() and p.stat().st_mtime > built:
                return True
        except OSError:
            continue
    return False


def _wait_for(predicate, what: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.4)
    _log(f"timed out waiting for {what} ({timeout:.0f}s)")
    return False


def _window_title() -> str:
    """Name the window after the app's branding, so a rebranded fork's window matches."""
    try:
        import json

        with urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/branding", timeout=2) as r:
            b = json.loads(r.read().decode("utf-8"))
        return b.get("product") or b.get("name") or "Test & Measurement"
    except (OSError, ValueError):
        return "Test & Measurement"


def _terminate_tree(proc: subprocess.Popen | None) -> None:
    """Kill a child AND its descendants. `npm.cmd` spawns Node (the real Vite); a plain
    terminate() on Windows kills only the .cmd wrapper and orphans Vite on its port."""
    if proc is None or proc.poll() is not None:
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:
        proc.terminate()


def _debug_enabled() -> bool:
    """Read app.json's debug.enabled — the Settings → Remote debugging switch."""
    try:
        import json
        cfg = json.loads((BACKEND / "config" / "app.json").read_text(encoding="utf-8"))
        return bool((cfg.get("debug") or {}).get("enabled"))
    except (OSError, ValueError):
        return False


def _mosquitto_exe() -> str | None:
    """Prefer the vendored broker (self-contained release), then PATH, then installs —
    mirrors deploy/run-local.ps1."""
    import shutil as _sh

    vendored = ROOT / "deploy" / "vendor" / "mosquitto" / "win64" / "mosquitto.exe"
    if vendored.is_file():
        return str(vendored)
    found = _sh.which("mosquitto")
    if found:
        return found
    for c in (r"C:\Program Files\mosquitto\mosquitto.exe",
              r"C:\Program Files (x86)\mosquitto\mosquitto.exe"):
        if Path(c).is_file():
            return c
    return None


# --------------------------------------------------------------------------- station
class Station:
    """Owns the child processes and a single, idempotent graceful shutdown."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.broker: subprocess.Popen | None = None
        self.backend: subprocess.Popen | None = None
        self.vite: subprocess.Popen | None = None
        self.debug_server: subprocess.Popen | None = None
        self._started_broker = False
        self._closing = False
        self._lock = threading.Lock()

    # ---- start ----------------------------------------------------------------
    def start_broker(self) -> None:
        if _port_open(BROKER_PORT):
            _log(f"broker already on :{BROKER_PORT} - leaving it alone")
            return
        exe = _mosquitto_exe()
        if exe is None:
            _log("mosquitto not found (deploy/fetch-mosquitto.ps1 vendors it) - "
                 "start a broker on :1883 manually")
            return
        conf = ROOT / "deploy" / "mosquitto.conf"
        cmd = [exe, "-v"] + (["-c", str(conf)] if conf.is_file() else [])
        self.broker = subprocess.Popen(cmd, cwd=str(ROOT))
        self._started_broker = True
        _log(f"broker started (pid={self.broker.pid})")

    def start_backend(self) -> None:
        # Go through launcher.py so the relaunch (exit 42) + staged-update loop keeps
        # working. New process group so we can target a graceful CTRL_BREAK at shutdown.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0
        self.backend = subprocess.Popen([sys.executable, "launcher.py"],
                                        cwd=str(BACKEND), creationflags=flags)
        _log(f"backend launcher started (pid={self.backend.pid})")

    def start_vite(self) -> None:
        npm = "npm.cmd" if IS_WIN else "npm"
        self.vite = subprocess.Popen([npm, "run", "dev"], cwd=str(FRONTEND))
        _log(f"vite dev server started (pid={self.vite.pid})")

    def start_debug_server(self) -> None:
        # Only when Settings → Remote debugging is switched on (app.json debug.enabled).
        # Kept a SEPARATE process from the backend so its lifecycle is independent — the
        # recorder must survive to watch the core while the core is broken.
        if not _debug_enabled():
            return
        self.debug_server = subprocess.Popen([sys.executable, "run_debug_server.py"],
                                             cwd=str(BACKEND))
        _log(f"debug server (flight recorder) started (pid={self.debug_server.pid})")

    # ---- stop -----------------------------------------------------------------
    def shutdown(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
        _log("shutting down ...")
        # Graceful backend teardown: CTRL_BREAK to the launcher's group reaches the
        # uvicorn child, which runs lifespan shutdown (controller → safe state), exits 0.
        if self.backend is not None and self.backend.poll() is None:
            try:
                if IS_WIN:
                    os.kill(self.backend.pid, signal.CTRL_BREAK_EVENT)
                else:
                    self.backend.send_signal(signal.SIGINT)
            except OSError:
                pass
            try:
                self.backend.wait(timeout=15)
            except subprocess.TimeoutExpired:
                _log("backend did not stop in time - terminating")
                self.backend.terminate()
        _terminate_tree(self.debug_server)
        _terminate_tree(self.vite)   # npm.cmd -> node: must kill the tree, not just the wrapper
        if self._started_broker:
            _terminate_tree(self.broker)
        _log("stopped")

    def backend_alive(self) -> bool:
        return self.backend is not None and self.backend.poll() is None


# --------------------------------------------------------------------------- window
def _open_window(station: Station, url: str) -> None:
    """Open the native pywebview window (blocks until closed). Falls back to the
    default browser if pywebview isn't installed."""
    try:
        import webview  # pywebview
    except ImportError:
        _log("pywebview not installed - opening the default browser instead "
             '(install it with:  pip install -e "backend[desktop]")')
        webbrowser.open(url)
        # Keep the process alive supervising the stack until the backend exits.
        while station.backend_alive():
            time.sleep(0.5)
        return

    title = _window_title()
    window = webview.create_window(
        title, url,
        width=1440, height=900,
        fullscreen=station.args.fullscreen,
        frameless=station.args.frameless,
        text_select=True,
    )

    # If the app is shut down from inside the UI (backend exits 0 → launcher stops),
    # close the window so station.py can fall through to cleanup.
    def _watch_backend() -> None:
        while station.backend_alive():
            time.sleep(0.5)
        if not station._closing:
            _log("backend exited (UI shutdown) - closing window")
            try:
                window.destroy()
            except Exception:  # noqa: BLE001 — window may already be gone
                pass

    threading.Thread(target=_watch_backend, daemon=True).start()
    webview.start()  # blocks on the main thread until the window is closed


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="One-click station launcher.")
    ap.add_argument("--dev", action="store_true",
                    help="development: start Vite + HMR on :5173 and point the window there")
    ap.add_argument("--browser", action="store_true",
                    help="open the default browser instead of a native window")
    ap.add_argument("--no-window", action="store_true",
                    help="run the services only (no window/browser)")
    ap.add_argument("--fullscreen", action="store_true", help="open the window fullscreen (kiosk)")
    ap.add_argument("--frameless", action="store_true", help="open the window without a frame")
    ap.add_argument("--build", action="store_true",
                    help="build the frontend before launching (production mode)")
    args = ap.parse_args()

    # Dev points at Vite; use `localhost` (Vite binds that — on Windows it may be IPv6
    # ::1, which a 127.0.0.1 probe would miss). Prod serves the built UI off the backend.
    ui_url = f"http://localhost:{VITE_PORT}" if args.dev else f"http://127.0.0.1:{BACKEND_PORT}"

    # Production mode serves the built bundle from the backend - make sure it exists
    # AND is current. From a source checkout a stale dist would silently serve an old
    # UI (features edited but not rebuilt); a frozen release has no frontend/src, so
    # its baked bundle is trusted as-is.
    if not args.dev:
        dist = FRONTEND / "dist" / "index.html"
        if args.build or not dist.is_file() or _frontend_stale(dist):
            reason = "forced" if args.build else ("missing" if not dist.is_file() else "stale")
            _log(f"building the frontend (bundle {reason}: npm run build) ...")
            npm = "npm.cmd" if IS_WIN else "npm"
            try:
                subprocess.run([npm, "run", "build"], cwd=str(FRONTEND), check=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                _log(f"frontend build failed ({exc}). Build it manually (cd frontend; npm install; "
                     "npm run build) or use --dev for HMR.")
                return 1

    station = Station(args)

    # Ctrl-C in this console → orderly shutdown of everything we started.
    signal.signal(signal.SIGINT, lambda *_: station.shutdown())

    try:
        station.start_broker()
        station.start_backend()
        station.start_debug_server()   # only if Settings → Remote debugging is on
        if args.dev:
            station.start_vite()

        # The backend is essential — if it never comes up, nothing works, so this stays fatal.
        if not _wait_for(lambda: _http_ok(HEALTH_URL), "backend :8000"):
            station.shutdown()
            return 1
        # The UI is NOT worth tearing down the stack for: a slow/failed dev server should
        # never kill the broker + backend. Wait, but on timeout just warn and open anyway —
        # the window/browser reconnects once Vite finishes (or once you fix a Vite error
        # shown above in this terminal, or point at the right port).
        ui_timeout = 120.0 if args.dev else 60.0
        if not _wait_for(lambda: _http_ok(ui_url), f"UI {ui_url}", timeout=ui_timeout):
            _log(f"UI not reachable at {ui_url} yet — opening anyway (it will connect when the "
                 "dev server is ready). If it never connects, check this terminal for a Vite "
                 "error or a different port (Vite uses 5174+ if 5173 is taken).")
        _log(f"ready -> {ui_url}")

        if args.no_window:
            while station.backend_alive():
                time.sleep(0.5)
        elif args.browser:
            webbrowser.open(ui_url)
            while station.backend_alive():
                time.sleep(0.5)
        else:
            _open_window(station, ui_url)   # blocks until the window closes
    finally:
        station.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

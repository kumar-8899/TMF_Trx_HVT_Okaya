"""The one station launcher — broker + supervised backend + desktop window, one file.

This is THE single entry point for running the app, in every layout:

    python station.py                 # source, production feel: backend serves the built UI, native
                                       # window, MAXIMIZED by default (not kiosk fullscreen)
    python station.py --dev           # source, development: Vite + HMR on :5173, window points there
    python station.py --browser       # open the default browser instead of a native window
    python station.py --fullscreen    # kiosk-style window (also --frameless)
    python station.py --no-window     # run the services only (headless), no window
    python station.py --build         # (source) rebuild the frontend before launching

The SAME file is Nuitka-compiled into **`run_station.exe`** (build_release.py `--track app`),
which bundles pywebview + the `launcher` module so a client PC needs NO system Python and NO
pip. It replaces the former separate `run_station.py`.

Mode is detected at runtime:
  * **Frozen** (`run_station.exe`, or a source checkout that already has `run.dist/run.exe`):
    the backend is `run.dist/run.exe`; supervise it via `launcher.Supervisor(run.dist, root)`
    in-process on a thread. No Vite, no build (there is no `frontend/src`).
  * **Source** (a dev checkout with `backend/` + `frontend/`): the backend is
    `backend/run.py`; supervise via `launcher.Supervisor(backend, backend)`; `--dev` starts
    Vite + HMR, and a stale/missing built bundle is rebuilt for production mode.

Either way the backend is supervised through `launcher.Supervisor`, so the "Relaunch to apply"
+ signed-update / rollback loop keeps working, and the broker + window lifecycle is identical.

Shutdown is graceful. Closing the window — via the OS title-bar close button, or the UI's "Exit
station" button — asks the supervisor to send the backend a CTRL_BREAK so its lifespan teardown
runs — modules stop and the Python controller drives every instrument to a safe state — before the
broker is stopped. The title-bar close button is bound explicitly (`window.events.closing`) so it
never just kills the window and leaves the backend/broker orphaned. Only what this launcher started
is stopped; an already-running broker is left alone.

pywebview is optional (`pip install -e "backend[desktop]"`). Without it, the launcher falls
back to the default browser and says so.
"""

from __future__ import annotations

import argparse
import json
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

# run_station.exe is PyInstaller-frozen (sets sys.frozen); also check __compiled__ (what a
# Nuitka build would set instead) since checking both costs nothing. Compute this FIRST and use
# sys.executable for ROOT when frozen: a PyInstaller onefile exe unpacks to a temp dir at
# runtime, so `__file__` would resolve there, not the exe's real location — sys.executable is
# the real running exe path (PyInstaller's own documented pattern for this).
COMPILED = "__compiled__" in globals() or bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if COMPILED else Path(__file__).resolve().parent
RUN_DIST = ROOT / "run.dist"
# Frozen = we run against a compiled run.dist/run.exe (either the frozen exe, or a source run
# from a deploy root that has one). Source = a dev checkout with backend/ + frontend/.
FROZEN = COMPILED or (RUN_DIST / "run.exe").is_file()
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


def _import_launcher():
    """The supervision loop module. Frozen `run_station.exe` bundles `launcher` (import the
    bundled copy); a source run imports it from `backend/`; a source run from a deploy
    root imports the copy shipped inside `run.dist`."""
    if not COMPILED:
        extra = str(BACKEND) if not FROZEN else str(RUN_DIST)
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import launcher
    return launcher


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    """True if the edge answered at all — a 404 (e.g. GET / without an html Accept, which the
    SPA middleware only serves to browser navigations) still means up."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True  # server responded (4xx) -> the edge is listening
    except OSError:
        return False


def _frontend_stale(dist_index: Path) -> bool:
    """True if the built bundle is older than the frontend source (a source checkout where
    someone edited the UI but didn't rebuild). A frozen release has no frontend/src, so its
    baked bundle is always trusted (returns False)."""
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
        with urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/branding", timeout=2) as r:
            b = json.loads(r.read().decode("utf-8"))
        return b.get("product") or b.get("name") or "Test & Measurement"
    except (OSError, ValueError):
        return "Test & Measurement"


def _window_icon() -> str | None:
    """The app icon for the window title bar + taskbar. Frozen: the built SPA ships favicon.ico
    at run.dist/frontend. Source: the fork's own frontend/public (or built dist) favicon."""
    candidates = (
        [RUN_DIST / "frontend" / "favicon.ico", RUN_DIST / "frontend" / "app-icon.png"]
        if FROZEN else
        [FRONTEND / "public" / "favicon.ico", FRONTEND / "dist" / "favicon.ico"]
    )
    return next((str(p) for p in candidates if p.is_file()), None)


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
    """Read app.json's debug.enabled — the Settings → Remote debugging switch. The live config is
    under the external deploy root when frozen (`ROOT/config`), under `backend/config` from source."""
    try:
        live = (ROOT if FROZEN else BACKEND) / "config" / "app.json"
        cfg = json.loads(live.read_text(encoding="utf-8"))
        return bool((cfg.get("debug") or {}).get("enabled"))
    except (OSError, ValueError):
        return False


def _mosquitto_exe() -> str | None:
    """Prefer the vendored broker (self-contained release), then PATH, then common installs."""
    import shutil as _sh

    vendored = (RUN_DIST if FROZEN else ROOT / "deploy") / "vendor" / "mosquitto" / "win64" / "mosquitto.exe"
    if vendored.is_file():
        return str(vendored)
    found = _sh.which("mosquitto")
    if found:
        return found
    for c in (r"D:\tools\mosquitto\mosquitto.exe",
              r"C:\Program Files\mosquitto\mosquitto.exe",
              r"C:\Program Files (x86)\mosquitto\mosquitto.exe"):
        if Path(c).is_file():
            return c
    return None


def _broker_cmd(exe: str) -> list[str]:
    """Prefer a loopback conf: the one vendored beside the exe, else deploy/mosquitto.conf in a
    source checkout. Mosquitto 2.x with NO config refuses anonymous clients, so the conf is
    load-bearing (`listener 1883 127.0.0.1` + `allow_anonymous true`); fall back to `-v`."""
    for conf in (Path(exe).with_name("mosquitto.conf"), ROOT / "deploy" / "mosquitto.conf"):
        if conf.is_file():
            return [exe, "-c", str(conf)]
    return [exe, "-v"]


# --------------------------------------------------------------------------- station
class Station:
    """Owns the child processes + the in-process backend supervisor, and a single, idempotent
    graceful shutdown."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.broker: subprocess.Popen | None = None
        self.vite: subprocess.Popen | None = None
        self.debug_server: subprocess.Popen | None = None
        self.supervisor = None                          # launcher.Supervisor (in-process)
        self._sup_thread: threading.Thread | None = None
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
            _log("mosquitto not found (deploy/fetch-mosquitto.ps1 vendors it) - the app runs, but "
                 "MQTT features stay offline until a broker is on :1883")
            return
        self.broker = subprocess.Popen(_broker_cmd(exe), cwd=str(ROOT))
        self._started_broker = True
        _log(f"broker started (pid={self.broker.pid})")

    def start_backend(self) -> None:
        # Supervise the backend IN-PROCESS on a thread via launcher.Supervisor — the same loop
        # for source (`backend/run.py`) and frozen (`run.dist/run.exe`), so no system Python is
        # spawned in the frozen exe. The Supervisor spawns the backend itself, in its own process
        # group, and shuts it down gracefully on request_stop(). Source/dev shows the backend's
        # console (logs); the frozen windowed exe suppresses it.
        launcher = _import_launcher()
        live = RUN_DIST if FROZEN else BACKEND
        state_root = ROOT if FROZEN else BACKEND
        self.supervisor = launcher.Supervisor(live, state_root, show_backend_console=not FROZEN)
        self._sup_thread = threading.Thread(target=self.supervisor.run, daemon=True,
                                             name="tmf-supervisor")
        self._sup_thread.start()
        _log(f"backend supervisor started (in-process, {'frozen' if FROZEN else 'source'})")

    def start_vite(self) -> None:
        npm = "npm.cmd" if IS_WIN else "npm"
        self.vite = subprocess.Popen([npm, "run", "dev"], cwd=str(FRONTEND))
        _log(f"vite dev server started (pid={self.vite.pid})")

    def start_debug_server(self) -> None:
        # The flight recorder, when Settings → Remote debugging is on (app.json debug.enabled).
        # A SEPARATE process so its lifecycle is independent - the recorder must survive to watch the
        # core while the core is broken. Source: `python run_debug_server.py`. Installed (frozen):
        # `run.exe --debug-server` (FRAMEWORK CR A2 - it used to be source-only, so the feature built
        # for field debugging did nothing on a client PC).
        if self._closing or not _debug_enabled() or (
                self.debug_server is not None and self.debug_server.poll() is None):
            return
        if FROZEN:
            flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
            self.debug_server = subprocess.Popen(
                [str(RUN_DIST / "run.exe"), "--debug-server"], cwd=str(RUN_DIST),
                env={**os.environ, "TMF_STATE_DIR": str(ROOT)}, creationflags=flags)
        else:
            self.debug_server = subprocess.Popen([sys.executable, "run_debug_server.py"], cwd=str(BACKEND))
        _log(f"debug server (flight recorder) started (pid={self.debug_server.pid})")

    def supervise_debug_server(self) -> None:
        """Keep the recorder matching the Settings switch: start it when turned on, stop it when turned
        off, restart it if it dies. Runs on a daemon thread for the life of the station."""
        def loop() -> None:
            while not self._closing:
                try:
                    running = self.debug_server is not None and self.debug_server.poll() is None
                    if _debug_enabled() and not running:
                        if self.debug_server is not None:
                            _log(f"debug server exited (rc={self.debug_server.returncode}) - restarting")
                        self.start_debug_server()
                    elif running and not _debug_enabled():
                        _log("remote debugging switched off - stopping the debug server")
                        _terminate_tree(self.debug_server)
                        self.debug_server = None
                except Exception as exc:  # noqa: BLE001 - the watchdog must never die
                    _log(f"debug server watchdog: {exc}")
                time.sleep(5.0)
        threading.Thread(target=loop, daemon=True, name="tmf-debug-watchdog").start()

    # ---- stop -----------------------------------------------------------------
    def shutdown(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
        _log("shutting down ...")
        # Graceful backend teardown: the supervisor CTRL_BREAKs the backend child, which runs
        # lifespan shutdown (controller → safe state), then the supervision thread exits.
        if self.supervisor is not None:
            self.supervisor.request_stop()
        if self._sup_thread is not None and self._sup_thread.is_alive():
            self._sup_thread.join(timeout=20)
            if self._sup_thread.is_alive():
                _log("backend supervisor did not stop in time")
        _terminate_tree(self.debug_server)
        _terminate_tree(self.vite)   # npm.cmd -> node: must kill the tree, not just the wrapper
        if self._started_broker:
            _terminate_tree(self.broker)
        _log("stopped")

    def backend_alive(self) -> bool:
        # Watch the supervision thread, not a single child: it runs ACROSS exit-42 relaunches
        # (staged swaps), so a mid-update restart must NOT be read as "backend gone".
        return self._sup_thread is not None and self._sup_thread.is_alive()


# --------------------------------------------------------------------------- window
def _open_window(station: Station, url: str) -> None:
    """Open the native pywebview window (blocks until closed). Falls back to the default browser
    if pywebview isn't installed."""
    try:
        import webview  # pywebview
    except ImportError:
        _log('pywebview not installed - opening the default browser instead '
             '(install it with:  pip install -e "backend[desktop]")')
        webbrowser.open(url)
        while station.backend_alive():
            time.sleep(0.5)
        return

    window = webview.create_window(
        _window_title(), url,
        width=1440, height=900,
        maximized=not station.args.fullscreen,   # default: maximized, not kiosk-style fullscreen
        fullscreen=station.args.fullscreen,
        frameless=station.args.frameless,
        text_select=True,
    )

    # If the app is shut down from inside the UI (backend exits 0 → supervisor stops), close the
    # window so main() can fall through to cleanup.
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

    # The reverse direction: the user clicks the OS title-bar close (X) button. Bind it explicitly
    # rather than relying on webview.start() merely returning afterwards — a bare window destroy
    # must not race ahead of (or skip) the same graceful teardown "Exit station" triggers. Runs the
    # shutdown on a background thread so the window itself closes immediately; station.shutdown()
    # is idempotent (guarded by station._lock/_closing) so this can't double-run with the `finally`
    # in main().
    def _on_closing() -> None:
        _log("window closed (title bar) - shutting down cleanly")
        threading.Thread(target=station.shutdown, daemon=True).start()

    window.events.closing += _on_closing
    icon = _window_icon()
    start_kw = {"icon": icon} if icon else {}
    try:
        webview.start(**start_kw)  # blocks on the main thread until the window is closed
    except TypeError:
        webview.start()            # older pywebview without the icon= param


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="The one station launcher (source + frozen).")
    ap.add_argument("--dev", action="store_true",
                    help="development (source only): start Vite + HMR on :5173 and point the window there")
    ap.add_argument("--browser", action="store_true",
                    help="open the default browser instead of a native window")
    ap.add_argument("--no-window", action="store_true", help="run the services only (no window/browser)")
    ap.add_argument("--fullscreen", action="store_true",
                    help="open the window fullscreen (kiosk); default without this flag is maximized")
    ap.add_argument("--frameless", action="store_true", help="open the window without a frame")
    ap.add_argument("--build", action="store_true",
                    help="(source) build the frontend before launching (production mode)")
    args = ap.parse_args()

    if FROZEN and (args.dev or args.build):
        _log("--dev/--build are source-checkout only (a frozen station has no frontend/src or npm) "
             "- ignoring")
        args.dev = args.build = False
    if FROZEN and not (RUN_DIST / "run.exe").is_file():
        _log(f"run.dist not found under {ROOT} - run this from the station root (beside run.dist).")
        return 1

    # Dev points at Vite; use `localhost` (Vite binds that — on Windows it may be IPv6 ::1, which
    # a 127.0.0.1 probe would miss). Every other mode serves the built UI off the backend.
    ui_url = f"http://localhost:{VITE_PORT}" if args.dev else f"http://127.0.0.1:{BACKEND_PORT}"

    # Production mode (source) serves the built bundle from the backend - make sure it exists AND
    # is current. A stale dist would silently serve an old UI (edited but not rebuilt); a frozen
    # release has no frontend/src, so its baked bundle is trusted as-is.
    if not FROZEN and not args.dev:
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
        station.start_debug_server()   # only if Settings → Remote debugging is on (source AND installed)
        station.supervise_debug_server()
        if args.dev:
            station.start_vite()

        # The backend is essential — if it never comes up, nothing works, so this stays fatal.
        boot_timeout = 90.0 if FROZEN else 60.0
        if not _wait_for(lambda: _http_ok(HEALTH_URL), "backend :8000", timeout=boot_timeout):
            station.shutdown()
            return 1
        # The UI is NOT worth tearing down the stack for: a slow/failed dev server should never
        # kill the broker + backend. On timeout just warn and open anyway — the window/browser
        # reconnects once Vite finishes (or once you fix a Vite error shown in this terminal).
        ui_timeout = 120.0 if args.dev else 60.0
        if not _wait_for(lambda: _http_ok(ui_url), f"UI {ui_url}", timeout=ui_timeout):
            _log(f"UI not reachable at {ui_url} yet — opening anyway (it will connect when the "
                 "server is ready). If it never connects, check this terminal for an error or a "
                 "different port (Vite uses 5174+ if 5173 is taken).")
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

r"""Windowed entry for the FROZEN station — broker (if present) + supervised backend + native window.

The frozen deploy has no `backend/` source and no Vite: the backend is `run.dist\run.exe`,
which serves the built SPA on one origin (http://127.0.0.1:8000). This launcher supervises it
through `run.dist\launcher.py` (so the exit-42 / staged-update / rollback loop keeps working)
and opens the UI in a native **pywebview** window.

    python run_station.py               # native window (default)
    python run_station.py --browser     # default browser instead of a window
    python run_station.py --no-window    # services only (headless)
    python run_station.py --fullscreen   # kiosk window   (also --frameless)

Run it from the station root (this file's dir) — the launcher renames run.dist during a swap,
so the working directory must be the parent. Needs a Python on PATH (the launcher is the
supervisor; run.exe is the frozen backend). Closing the window shuts the backend down
gracefully (CTRL_BREAK → lifespan teardown) before exit.
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

ROOT = Path(__file__).resolve().parent          # station/  (parent of run.dist)
RUN_DIST = ROOT / "run.dist"
IS_WIN = sys.platform == "win32"

BACKEND_PORT = 8000
BROKER_PORT = 1883
HEALTH_URL = f"http://127.0.0.1:{BACKEND_PORT}/healthz"
UI_URL = f"http://127.0.0.1:{BACKEND_PORT}"


def _log(msg: str) -> None:
    print(f"station: {msg}", flush=True)


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except OSError:
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
    try:
        with urllib.request.urlopen(f"{UI_URL}/branding", timeout=2) as r:
            b = json.loads(r.read().decode("utf-8"))
        return b.get("product") or b.get("name") or "Test & Measurement"
    except (OSError, ValueError):
        return "Test & Measurement"


def _terminate_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:
        proc.terminate()


def _mosquitto_exe() -> str | None:
    import shutil as _sh
    vendored = RUN_DIST / "vendor" / "mosquitto" / "win64" / "mosquitto.exe"
    if vendored.is_file():
        return str(vendored)
    found = _sh.which("mosquitto")
    if found:
        return found
    for c in (r"D:\tools\mosquitto\mosquitto.exe",          # dev.ps1 location
              r"C:\Program Files\mosquitto\mosquitto.exe",
              r"C:\Program Files (x86)\mosquitto\mosquitto.exe"):
        if Path(c).is_file():
            return c
    return None


class Station:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.broker: subprocess.Popen | None = None
        self.backend: subprocess.Popen | None = None
        self._started_broker = False
        self._closing = False
        self._lock = threading.Lock()

    def start_broker(self) -> None:
        if _port_open(BROKER_PORT):
            _log(f"broker already on :{BROKER_PORT} - leaving it alone")
            return
        exe = _mosquitto_exe()
        if exe is None:
            _log("mosquitto not found - the app runs, but MQTT features stay offline "
                 "(start a broker on :1883 if you need the controller/bridge)")
            return
        self.broker = subprocess.Popen([exe, "-v"], cwd=str(ROOT))
        self._started_broker = True
        _log(f"broker started (pid={self.broker.pid})")

    def start_backend(self) -> None:
        # Supervise the frozen backend through launcher.py (keeps the exit-42 / update /
        # rollback loop working). CWD = station root so a swap can rename run.dist. New
        # process group so we can send a graceful CTRL_BREAK at shutdown.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0
        self.backend = subprocess.Popen([sys.executable, str(RUN_DIST / "launcher.py")],
                                        cwd=str(ROOT), creationflags=flags)
        _log(f"backend launcher started (pid={self.backend.pid})")

    def shutdown(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
        _log("shutting down ...")
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
                _terminate_tree(self.backend)
        if self._started_broker:
            _terminate_tree(self.broker)
        _log("stopped")

    def backend_alive(self) -> bool:
        return self.backend is not None and self.backend.poll() is None


def _open_window(station: Station, url: str) -> None:
    try:
        import webview  # pywebview
    except ImportError:
        _log('pywebview not installed - opening the default browser instead '
             '(install it with:  pip install "pywebview>=5.0")')
        webbrowser.open(url)
        while station.backend_alive():
            time.sleep(0.5)
        return

    window = webview.create_window(
        _window_title(), url,
        width=1440, height=900,
        fullscreen=station.args.fullscreen,
        frameless=station.args.frameless,
        text_select=True,
    )

    def _watch_backend() -> None:
        while station.backend_alive():
            time.sleep(0.5)
        if not station._closing:
            _log("backend exited (UI shutdown) - closing window")
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_watch_backend, daemon=True).start()
    webview.start()  # blocks on the main thread until the window is closed


def main() -> int:
    ap = argparse.ArgumentParser(description="Frozen-station windowed launcher.")
    ap.add_argument("--browser", action="store_true", help="open the default browser instead of a window")
    ap.add_argument("--no-window", action="store_true", help="run services only (no window)")
    ap.add_argument("--fullscreen", action="store_true", help="open the window fullscreen (kiosk)")
    ap.add_argument("--frameless", action="store_true", help="open the window without a frame")
    args = ap.parse_args()

    if not (RUN_DIST / "launcher.py").is_file() or not (RUN_DIST / "run.exe").is_file():
        _log(f"run.dist not found under {ROOT} - run this from the station root.")
        return 1

    station = Station(args)
    signal.signal(signal.SIGINT, lambda *_: station.shutdown())

    try:
        station.start_broker()
        station.start_backend()
        if not _wait_for(lambda: _http_ok(HEALTH_URL), "backend :8000", timeout=90.0):
            station.shutdown()
            return 1
        _log(f"ready -> {UI_URL}")

        if args.no_window:
            while station.backend_alive():
                time.sleep(0.5)
        elif args.browser:
            webbrowser.open(UI_URL)
            while station.backend_alive():
                time.sleep(0.5)
        else:
            _open_window(station, UI_URL)
    finally:
        station.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

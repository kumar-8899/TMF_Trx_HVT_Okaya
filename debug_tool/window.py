"""The operator's window: a native pywebview window on the tool's own page (the pattern `station.py` uses), with the default browser
as a fallback. Closing the window shuts the tool down - sharing stops, pending requests are denied - so a tool that was left open
and forgotten cannot keep a session alive invisibly."""

from __future__ import annotations

import threading
import time
import webbrowser

import httpx


def wait_until_up(url: str, server, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if getattr(server, "started", False):
            return True
        try:
            if httpx.get(url.rstrip("/") + "/healthz", timeout=1).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


def run_with_window(server, url: str, *, browser_only: bool = False) -> None:
    """Run uvicorn in a thread and the window on the main thread (pywebview requires the main thread); stop the server when the
    window closes. Without pywebview (or with --browser) open the default browser and run until Ctrl-C."""
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    if not wait_until_up(url, server):
        server.should_exit = True
        thread.join(5)
        raise SystemExit("the tool did not come up - see the messages above")
    try:
        if browser_only:
            raise ImportError("--browser")
        import webview                                               # pywebview (optional: pip install -e "backend[desktop]")
    except ImportError as exc:
        if str(exc) != "--browser":
            print('pywebview is not installed - opening the default browser instead (pip install -e "backend[desktop]")')
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.should_exit = True
        thread.join(10)
        return
    webview.create_window("TMF Debug Tool", url, width=1280, height=860, text_select=True)
    try:
        webview.start()                                              # blocks until the window is closed
    finally:
        server.should_exit = True
        thread.join(15)

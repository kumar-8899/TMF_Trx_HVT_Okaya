"""REST + WebSocket client for the Debug Server sidecar (REMOTE_DEBUG.md §8).

Thin, typed-ish wrappers over the existing sidecar surface. No backend import — the
only knowledge shared with the sidecar is the wire shape of a captured record.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

import httpx

DEFAULT_PORT = 8001


class DebugClient:
    """Synchronous REST client + an async WS tail. `host` is a bench address."""

    def __init__(self, host: str, *, token: str | None = None, port: int = DEFAULT_PORT,
                 scheme: str = "http", timeout: float = 15.0, transport: Any = None) -> None:
        self.host = host
        self.port = port
        self.scheme = scheme
        self.token = token
        self.base = f"{scheme}://{host}:{port}"
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        # A `transport` (e.g. httpx.ASGITransport) lets tests drive the sidecar app
        # in-process; production leaves it None for real network calls.
        self._http = httpx.Client(base_url=self.base, headers=self._headers,
                                  timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    # --- REST --------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        r = self._http.get(path, params=clean)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> Any:
        r = self._http.post(path, json=body)
        r.raise_for_status()
        return r.json()

    def health(self) -> dict:
        # /debug/health is unauthenticated (ops liveness) — no token needed.
        r = self._http.get("/debug/health")
        r.raise_for_status()
        return r.json()

    def events(self, *, since: int | None = None, level: str | None = None,
               subsystem: str | None = None, topic: str | None = None, trace: str | None = None,
               kind: str | None = None, text: str | None = None, limit: int = 5000) -> list[dict]:
        return self._get("/debug/events", {
            "since": since, "level": level, "subsystem": subsystem, "topic": topic,
            "trace": trace, "kind": kind, "text": text, "limit": limit})

    def traces(self) -> list[dict]:
        return self._get("/debug/traces")

    def requests(self, *, status: str | None = None) -> list[dict]:
        return self._get("/debug/requests", {"status": status})

    def liveness(self) -> list[dict]:
        return self._get("/debug/liveness")

    def violations(self) -> list[dict]:
        return self._get("/debug/violations")

    # Rolling sink + snapshots + level land in PR-C/E/F; the client methods are added
    # there. `events()` (the in-memory ring) is the PR-A source for `pull`.

    def set_level(self, subsystem: str, level: str) -> dict:
        return self._post("/debug/level", {"subsystem": subsystem, "level": level})

    def levels(self) -> dict:
        return self._get("/debug/level")

    def snapshots(self) -> list[dict]:
        return self._get("/debug/snapshots")

    def snapshot(self, snap_id: str) -> str:
        r = self._http.get(f"/debug/snapshot/{snap_id}")
        r.raise_for_status()
        return r.text

    def rolling(self, *, since: float | None = None, until: float | None = None,
                run_id: str | None = None) -> Iterable[dict]:
        """Stream the rolling JSONL sink (PR-C). Yields one record dict per line."""
        clean = {k: v for k, v in {"since": since, "until": until, "run_id": run_id}.items()
                 if v is not None}
        with self._http.stream("GET", "/debug/rolling", params=clean, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    yield json.loads(line)

    # --- WS tail -----------------------------------------------------------

    async def watch(self, *, level: str | None = None, subsystem: str | None = None,
                    topic: str | None = None) -> AsyncIterator[dict]:
        """Live tail of /debug/stream. Yields each record as it arrives."""
        import websockets

        ws_scheme = "wss" if self.scheme == "https" else "ws"
        qs = {"token": self.token, "level": level, "subsystem": subsystem, "topic": topic}
        query = "&".join(f"{k}={v}" for k, v in qs.items() if v is not None)
        url = f"{ws_scheme}://{self.host}:{self.port}/debug/stream" + (f"?{query}" if query else "")
        async with websockets.connect(url) as ws:
            async for raw in ws:
                yield json.loads(raw)

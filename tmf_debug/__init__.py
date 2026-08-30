"""tmf-debug — the laptop client for the TMF Debug Server (REMOTE_DEBUG.md §8).

Imports nothing from `backend/`. Talks to a bench's sidecar over its existing REST +
WebSocket surface, writes captures + digests into `.debug/` at the app-repo root.
"""

__version__ = "0.1.0"

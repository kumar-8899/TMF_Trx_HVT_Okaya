"""Wire envelope helpers — the request/reply convention (LABVIEW_BRIDGE.md §5).

A command arrives on `tmf/{station}/cmd/{op}` as JSON `{id, op, args, reply_to}`. The
reply goes back to `reply_to` carrying the same `id` so a 3.1.1 responder needs no
MQTT-5 features. These are pure functions so the envelope is unit-testable without a
broker. (A shared wire-schema package arrives when payloads gain structure, C3+.)"""

from __future__ import annotations

import json


def op_from_topic(topic: str) -> str | None:
    """`tmf/{station}/cmd/{op}` -> op. Anything else -> None."""
    parts = topic.split("/")
    if len(parts) == 4 and parts[0] == "tmf" and parts[2] == "cmd":
        return parts[3]
    return None


def decode(payload: bytes | str | None) -> dict | None:
    if not payload:
        return None
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def reply_payload(request: dict | None, result: dict | None = None,
                  error: dict | None = None) -> dict:
    """Build the reply that goes to the request's `reply_to`. On success the result
    dict is merged in at the top level (so `hello.echo` echoes flat); on failure a
    structured RFC-7807-ish error rides under `error` (LABVIEW_BRIDGE.md §11)."""
    rid = (request or {}).get("id")
    if error is not None:
        return {"id": rid, "ok": False, "error": error}
    return {"id": rid, "ok": True, **(result or {})}


def reply_topic(request: dict | None) -> str | None:
    return (request or {}).get("reply_to")

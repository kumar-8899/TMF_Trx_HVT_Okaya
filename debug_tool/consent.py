"""Consent: who may reach the Debug Tool, until when, and which actions a human approved (docs/DEBUG_TOOL.md).

Three layers, all in this module and all pure (injectable clock; no network, no UI):

  SharingState   the operator turns Sharing ON for a bounded time; that issues the bearer token Claude Code uses.
                 Off by default, never persisted (a restart resets to Off), expires on its own, one Stop button.
  ApprovalQueue  every ACTION (script, probe, file read, level change, capture, export) is held here until a human at
                 the client PC clicks Approve. One decision authorises exactly one request - there are no standing
                 approvals. No answer within the timeout is a denial. Stopping the session denies everything pending.
  AccessLog      a size-capped JSONL record of every remote request, decision and outcome (who/what/when/result).

The approvals API that calls `ApprovalQueue.decide` is reachable ONLY by the operator (loopback + the per-process
operator key); the MCP bearer token can never approve its own requests - see app.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

MAX_SHARE_HOURS = 24.0
DEFAULT_SHARE_HOURS = 4.0
DEFAULT_APPROVAL_TIMEOUT_S = 120.0

#: Operations that need a per-call human approval ("action"), vs those covered by the sharing session ("passive").
ACTION_KINDS = frozenset({"run_script", "read_file", "instrument_probe", "instrument_poll", "level_set",
                          "capture", "export"})


class ConsentError(Exception):
    pass


# --------------------------------------------------------------------------------------------- access log

class AccessLog:
    """Append-only JSONL, rolled once at `max_bytes` (one `.1` backup), safe across threads."""

    def __init__(self, path: Path | str, *, max_bytes: int = 2_000_000, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._clock = clock
        self._lock = threading.Lock()

    def write(self, **fields) -> dict:
        rec = {"ts": round(self._clock(), 3), **fields}
        line = json.dumps(rec, default=str, ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_file() and self.path.stat().st_size + len(line) > self.max_bytes:
                bak = self.path.with_suffix(self.path.suffix + ".1")
                bak.unlink(missing_ok=True)
                self.path.replace(bak)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
        return rec

    def tail(self, n: int = 50) -> list[dict]:
        with self._lock:
            files = [p for p in (self.path.with_suffix(self.path.suffix + ".1"), self.path) if p.is_file()]
            lines: deque[str] = deque(maxlen=n)
            for p in files:
                with p.open("r", encoding="utf-8", errors="replace") as fh:
                    lines.extend(fh)
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out


# --------------------------------------------------------------------------------------------- sharing

class SharingState:
    """Sharing On/Off with an expiry. The token is generated when sharing starts and is only ever held in memory."""

    def __init__(self, *, clock: Callable[[], float] = time.time, log: AccessLog | None = None) -> None:
        self._clock = clock
        self._log = log
        self._token: str | None = None
        self.expires_at: float | None = None
        self.started_at: float | None = None
        self.allow_during_run = False
        self.session: dict = {}                       # last remote caller: {remote, last_seen, requests}
        self._lock = threading.Lock()

    # -- control (operator) --------------------------------------------------
    def start(self, hours: float = DEFAULT_SHARE_HOURS, *, allow_during_run: bool = False) -> str:
        if not (0 < float(hours) <= MAX_SHARE_HOURS):
            raise ConsentError(f"sharing lasts between 0 and {MAX_SHARE_HOURS:g} hours")
        with self._lock:
            self._token = secrets.token_urlsafe(32)
            self.started_at = self._clock()
            self.expires_at = self.started_at + float(hours) * 3600.0
            self.allow_during_run = bool(allow_during_run)
            self.session = {}
            token = self._token
        if self._log:
            self._log.write(event="sharing_started", hours=hours, fingerprint=self.fingerprint())
        return token

    def stop(self, reason: str = "operator") -> None:
        with self._lock:
            was = self._token is not None
            self._token, self.expires_at, self.started_at, self.session = None, None, None, {}
        if was and self._log:
            self._log.write(event="sharing_stopped", reason=reason)

    # -- queries -------------------------------------------------------------
    def active(self) -> bool:
        with self._lock:
            if self._token is None or self.expires_at is None:
                return False
            if self._clock() >= self.expires_at:
                self._token = self.expires_at = self.started_at = None
                expired = True
            else:
                return True
        if expired and self._log:
            self._log.write(event="sharing_expired")
        return False

    def check_token(self, token: str | None) -> bool:
        """True only while sharing is active AND the token matches (constant-time compare)."""
        if not token or not self.active():
            return False
        with self._lock:
            return self._token is not None and hmac.compare_digest(token, self._token)

    def fingerprint(self) -> str | None:
        with self._lock:
            return hashlib.sha256(self._token.encode()).hexdigest()[:8] if self._token else None

    def touch(self, remote: str | None) -> None:
        with self._lock:
            s = self.session
            s["remote"] = remote
            s["last_seen"] = self._clock()
            s["requests"] = s.get("requests", 0) + 1

    def status(self) -> dict:
        on = self.active()
        with self._lock:
            return {"on": on, "expires_at": self.expires_at if on else None,
                    "seconds_left": max(0, int(self.expires_at - self._clock())) if on and self.expires_at else 0,
                    "fingerprint": hashlib.sha256(self._token.encode()).hexdigest()[:8] if on and self._token else None,
                    "allow_during_run": self.allow_during_run, "session": dict(self.session)}


# --------------------------------------------------------------------------------------------- approvals

@dataclass
class Decision:
    approved: bool
    reason: str                       # approved | denied | timeout | stopped
    id: str = ""
    by: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"approved": self.approved, "reason": self.reason, "id": self.id, "by": self.by, "extra": self.extra}


@dataclass
class _Pending:
    id: str
    kind: str
    summary: str
    details: dict
    created: float
    fut: asyncio.Future


class ApprovalQueue:
    def __init__(self, *, clock: Callable[[], float] = time.time, timeout_s: float = DEFAULT_APPROVAL_TIMEOUT_S,
                 log: AccessLog | None = None, history_size: int = 50) -> None:
        self._clock = clock
        self.timeout_s = timeout_s
        self._log = log
        self._pending: dict[str, _Pending] = {}
        self._history: deque[dict] = deque(maxlen=history_size)

    async def request(self, kind: str, summary: str, details: dict | None = None, *,
                      timeout_s: float | None = None, on_progress: Callable[[str], None] | None = None) -> Decision:
        """Block until a human decides. Returns the Decision; never raises on deny/timeout."""
        rid = secrets.token_hex(6)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = _Pending(rid, kind, summary, details or {}, self._clock(), fut)
        if self._log:
            self._log.write(event="approval_requested", id=rid, kind=kind, summary=summary, details=details or {})
        if on_progress:
            on_progress(f"waiting for the operator to approve: {summary}")
        try:
            decision = await asyncio.wait_for(asyncio.shield(fut), timeout_s if timeout_s is not None else self.timeout_s)
        except asyncio.TimeoutError:
            decision = Decision(False, "timeout", rid)
        finally:
            p = self._pending.pop(rid, None)
        if not fut.done():
            fut.set_result(decision)
        self._record(rid, kind, summary, decision)
        return decision

    def pending(self) -> list[dict]:
        now = self._clock()
        return [{"id": p.id, "kind": p.kind, "summary": p.summary, "details": p.details,
                 "age_s": int(now - p.created), "timeout_s": self.timeout_s} for p in self._pending.values()]

    def decide(self, rid: str, approve: bool, *, by: str | None = None, extra: dict | None = None) -> bool:
        p = self._pending.get(rid)
        if p is None or p.fut.done():
            return False
        p.fut.set_result(Decision(bool(approve), "approved" if approve else "denied", rid, by, extra or {}))
        return True

    def deny_all(self, reason: str = "stopped") -> int:
        n = 0
        for p in list(self._pending.values()):
            if not p.fut.done():
                p.fut.set_result(Decision(False, reason, p.id))
                n += 1
        return n

    def history(self) -> list[dict]:
        return list(self._history)

    def _record(self, rid: str, kind: str, summary: str, d: Decision) -> None:
        row = {"ts": round(self._clock(), 3), "id": rid, "kind": kind, "summary": summary, "decision": d.reason, "by": d.by}
        self._history.append(row)
        if self._log:
            self._log.write(event="approval_decided", id=rid, kind=kind, summary=summary, decision=d.reason, by=d.by,
                            approved=d.approved, extra=d.extra)

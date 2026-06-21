"""Check registry — the pluggable unit (HEALTH_CHECK.md §2).

A check has a descriptor (static metadata, here) and an executor. `web` and the
Python-runnable `bridge` connectivity checks have a local async executor; true
`hardware`/`bridge` checks with no local executor are dispatched over the bridge
as `health.check.<id>` (HEALTH_CHECK.md §12) and report `unavailable` when the
seam/LabVIEW handler is absent (§2.4).
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class CheckDescriptor:
    id: str
    domain: str                 # web | bridge | hardware
    title: str
    description: str = ""
    disruptive: bool = False
    timeout_ms: int = 5000
    severity: str = "critical"  # critical | warning | info
    tags: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "id": self.id, "domain": self.domain, "title": self.title,
            "description": self.description, "disruptive": self.disruptive,
            "timeout_ms": self.timeout_ms, "severity": self.severity,
            "tags": list(self.tags), "requires": list(self.requires),
        }


# Executor returns the verdict body: {status, summary, data, error}. The
# sequencer wraps timing, signature, and the envelope around it.
Executor = Callable[..., Awaitable[dict]]

_DESCRIPTORS: dict[str, CheckDescriptor] = {}
_EXECUTORS: dict[str, Executor] = {}


def register(descriptor: CheckDescriptor):
    def deco(fn: Executor) -> Executor:
        _DESCRIPTORS[descriptor.id] = descriptor
        _EXECUTORS[descriptor.id] = fn
        return fn
    return deco


def descriptors() -> dict[str, CheckDescriptor]:
    return dict(_DESCRIPTORS)


def executor(check_id: str) -> Executor | None:
    return _EXECUTORS.get(check_id)


# --- built-in checks (R1) --------------------------------------------------


@register(CheckDescriptor(
    id="web.db_writable", domain="web", title="Database writable", severity="critical",
    description="Round-trips a scratch record through the repository.", tags=["web", "storage"]))
async def _db_writable(core, cfg, params) -> dict:
    probe = {"probe": "health", "ts": time.time()}
    await core.db.repo.put("health_probe", probe, id="__probe__", summary="health probe")
    rec = await core.db.repo.get("health_probe", "__probe__")
    ok = bool(rec and rec["data"].get("probe") == "health")
    return {"status": "pass" if ok else "fail",
            "summary": "repository read/write OK" if ok else "probe round-trip mismatch",
            "data": {"ok": ok}, "error": None}


@register(CheckDescriptor(
    id="web.disk_space", domain="web", title="Disk space", severity="warning",
    description="Free space under the data root is above the configured minimum.", tags=["web", "storage"]))
async def _disk_space(core, cfg, params) -> dict:
    root = cfg.get("data_root", "data")
    min_gb = float(cfg.get("disk_min_gb", 1.0))
    usage = shutil.disk_usage(root)
    free_gb = usage.free / (1024 ** 3)
    ok = free_gb >= min_gb
    return {"status": "pass" if ok else "fail",
            "summary": f"{free_gb:.1f} GB free (min {min_gb} GB)",
            "data": {"free_gb": round(free_gb, 2), "min_gb": min_gb}, "error": None}


@register(CheckDescriptor(
    id="bridge.online", domain="bridge", title="Bridge link online", severity="critical",
    description="The MQTT bridge is connected and LabVIEW reports status=online.", tags=["bridge"]))
async def _bridge_online(core, cfg, params) -> dict:
    if core.bridge is None:
        return {"status": "unavailable", "summary": "no bridge configured", "data": {}, "error": None}
    if core.bridge.online:
        return {"status": "pass", "summary": "bridge online", "data": {"online": True}, "error": None}
    detail = "broker connected, link not online" if core.bridge.connected else "broker not connected"
    return {"status": "fail", "summary": detail, "data": {"online": False, "connected": core.bridge.connected}, "error": None}


@register(CheckDescriptor(
    id="bridge.roundtrip", domain="bridge", title="Bridge round-trip", severity="warning",
    description="hello.echo returns within budget over the bridge.", tags=["bridge"],
    requires=["bridge.online"]))
async def _bridge_roundtrip(core, cfg, params) -> dict:
    if core.bridge is None or not core.bridge.online:
        return {"status": "unavailable", "summary": "bridge not online", "data": {}, "error": None}
    t0 = time.time()
    reply = await core.bridge.request("hello.echo", {"from": "health"})
    ms = (time.time() - t0) * 1000
    ok = bool(reply.get("ok", True))
    return {"status": "pass" if ok else "fail",
            "summary": f"round-trip {ms:.0f} ms", "data": {"elapsed_ms": round(ms, 1)}, "error": None}

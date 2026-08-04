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
    # operator-facing metadata (Health UX): plain-language purpose, the business
    # impact if it fails, the steps to fix it, and the business-function group.
    purpose: str = ""
    impact: str = ""
    user_action: list[str] = field(default_factory=list)
    group: str = "System"           # business group: Core Software / Production Systems / Test Equipment / External Systems
    # instance templating (§4.4): a base check expands to one concrete check per
    # matching instance at load. `select` filters instances (by_family/by_capability).
    instance_templated: bool = False
    select: dict = field(default_factory=dict)
    base_id: str | None = None      # set on an expanded concrete check
    instance_id: str | None = None  # set on an expanded concrete check

    def public(self) -> dict:
        return {
            "id": self.id, "domain": self.domain, "title": self.title,
            "description": self.description, "disruptive": self.disruptive,
            "timeout_ms": self.timeout_ms, "severity": self.severity,
            "purpose": self.purpose, "impact": self.impact, "user_action": list(self.user_action),
            "group": self.group, "tags": list(self.tags), "requires": list(self.requires),
            "instance_templated": self.instance_templated,
            "base_id": self.base_id, "instance_id": self.instance_id,
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
    id="web.db_writable", domain="web", title="Database", severity="critical", group="Core Software",
    description="Round-trips a scratch record through the repository.", tags=["web", "storage"],
    purpose="Verify the database accepts reads and writes.",
    impact="Test reports and records cannot be saved.",
    user_action=["Check free disk space", "Check the data-folder permissions", "Restart the app", "Re-test"]))
async def _db_writable(core, cfg, params) -> dict:
    probe = {"probe": "health", "ts": time.time()}
    await core.db.repo.put("health_probe", probe, id="__probe__", summary="health probe")
    rec = await core.db.repo.get("health_probe", "__probe__")
    ok = bool(rec and rec["data"].get("probe") == "health")
    return {"status": "pass" if ok else "fail",
            "summary": "repository read/write OK" if ok else "probe round-trip mismatch",
            "data": {"ok": ok}, "error": None}


@register(CheckDescriptor(
    id="web.disk_space", domain="web", title="Disk space", severity="warning", group="Core Software",
    description="Free space under the data root is above the configured minimum.", tags=["web", "storage"],
    purpose="Ensure enough free disk for data and logs.",
    impact="New reports and logs may fail to save.",
    user_action=["Free up disk space", "Re-test"]))
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
    id="instruments.python", domain="web", title="Test instruments", severity="warning", group="Test Equipment",
    description="Every Python-owned instrument instance is connected (INSTRUMENT_LIBRARY §6).",
    tags=["instruments"],
    purpose="Configured Python instruments are connected.",
    impact="Tests that use a disconnected instrument will fail.",
    user_action=["Check instrument power + cabling", "Verify the instance connection params", "Re-test"]))
async def _python_instruments(core, cfg, params) -> dict:
    get = getattr(core, "get_contract", None)
    if get is None:
        return {"status": "unavailable", "summary": "no contract registry", "data": {}, "error": None}
    try:
        mod = get("variables")
    except KeyError:
        return {"status": "skipped", "summary": "variables module not loaded", "data": {}, "error": None}
    st = mod.instance_status()
    if not st:
        return {"status": "skipped", "summary": "no instruments configured", "data": {"instances": 0}, "error": None}
    bad = [s["id"] for s in st if s["state"] != "connected"]
    ok = not bad
    return {"status": "pass" if ok else "fail",
            "summary": f"{len(st) - len(bad)}/{len(st)} connected" + ("" if ok else f"; issues: {bad}"),
            "data": {"total": len(st), "bad": bad},
            "error": None if ok else {"category": "instrument", "code": "not_connected"}}


def _station(core, params):
    return params.get("station") or core.station


def _link_online(core, station) -> bool:
    ls = getattr(core.bridge, "link_status", None)
    return ls(station) == "online" if ls else bool(getattr(core.bridge, "online", False))


@register(CheckDescriptor(
    id="bridge.online", domain="bridge", title="LabVIEW engine", severity="critical", group="Production Systems",
    description="The MQTT bridge is connected and LabVIEW reports status=online.", tags=["bridge"],
    purpose="Verify the link to the LabVIEW controller.",
    impact="Tests cannot run.",
    user_action=["Start the LabVIEW Bridge", "Check the broker (Mosquitto) is running", "Re-test"]))
async def _bridge_online(core, cfg, params) -> dict:
    if core.bridge is None:
        return {"status": "unavailable", "summary": "no bridge configured", "data": {}, "error": None}
    st = _station(core, params)
    if _link_online(core, st):
        return {"status": "pass", "summary": f"{st} online", "data": {"online": True, "station": st}, "error": None}
    detail = "broker connected, link not online" if core.bridge.connected else "broker not connected"
    return {"status": "fail", "summary": f"{st}: {detail}",
            "data": {"online": False, "connected": core.bridge.connected, "station": st}, "error": None}


@register(CheckDescriptor(
    id="bridge.roundtrip", domain="bridge", title="Engine response", severity="warning", group="Production Systems",
    description="hello.echo returns within budget over the bridge.", tags=["bridge"],
    requires=["bridge.online"],
    purpose="The controller answers commands promptly.",
    impact="Tests may run slowly or stall.",
    user_action=["Check controller CPU/load", "Re-test"]))
async def _bridge_roundtrip(core, cfg, params) -> dict:
    st = _station(core, params)
    if core.bridge is None or not _link_online(core, st):
        return {"status": "unavailable", "summary": f"{st} not online", "data": {}, "error": None}
    t0 = time.time()
    reply = await core.bridge.request("hello.echo", {"from": "health"}, station=st)
    ms = (time.time() - t0) * 1000
    ok = bool(reply.get("ok", True))
    return {"status": "pass" if ok else "fail",
            "summary": f"round-trip {ms:.0f} ms", "data": {"elapsed_ms": round(ms, 1)}, "error": None}


def _reply_ts(reply: dict):
    return reply.get("ts") or (reply.get("result") or {}).get("ts") or (reply.get("echoed") or {}).get("ts")


@register(CheckDescriptor(
    id="bridge.clock_skew", domain="bridge", title="Clock alignment", severity="warning", group="Production Systems",
    description="LabVIEW timestamp vs Python within tolerance (skew corrupts every correlation).",
    tags=["bridge"], requires=["bridge.online"],
    purpose="Controller and PC clocks agree.",
    impact="Timestamps and result correlation may be wrong.",
    user_action=["Sync the controller and PC system clocks", "Re-test"]))
async def _bridge_clock_skew(core, cfg, params) -> dict:
    st = _station(core, params)
    if core.bridge is None or not _link_online(core, st):
        return {"status": "unavailable", "summary": f"{st} not online", "data": {}, "error": None}
    tol = float(cfg.get("clock_skew_tolerance_s", 2.0))
    reply = await core.bridge.request("hello.echo", {"from": "health"}, station=st)
    lv_ts = _reply_ts(reply)
    if lv_ts is None:
        return {"status": "error", "summary": "reply carried no timestamp", "data": {},
                "error": {"type": "about:blank", "title": "no ts in reply"}}
    skew = abs(time.time() - float(lv_ts))
    ok = skew <= tol
    return {"status": "pass" if ok else "fail",
            "summary": f"clock skew {skew:.2f}s (tolerance {tol}s)",
            "data": {"skew_s": round(skew, 3), "tolerance_s": tol}, "error": None}


# Dispatched over the bridge to a LabVIEW handler (no local executor): the
# controller answers `health.check.bridge.queue_depth` with a CheckVerdict
# (HEALTH_CHECK.md §12). Absent handler / offline bridge -> unavailable/timeout.
register(CheckDescriptor(
    id="bridge.queue_depth", domain="bridge", title="Engine queue", severity="warning", group="Production Systems",
    description="LabVIEW reports its inbound bridge queue is not backed up.",
    tags=["bridge"], requires=["bridge.online"],
    purpose="The controller is keeping up with commands.",
    impact="Commands may lag; tests can stall.",
    user_action=["Reduce station load", "Restart the controller if it persists"]))(None)


# --- hardware checks (R3) --------------------------------------------------
# Hardware I/O is LabVIEW-owned (PRINCIPLES §0): these have NO local executor and
# are dispatched per instance as health.check.<base> {instance_id} (§12). Each is
# instance-templated — one definition covers every instance of a family (§4.4).

def _hw(check_id, title, *, disruptive, severity, desc, requires, purpose, impact, user_action):
    register(CheckDescriptor(
        id=check_id, domain="hardware", title=title, description=desc,
        disruptive=disruptive, severity=severity, tags=["hardware"],
        requires=requires, instance_templated=True, group="Test Equipment",
        purpose=purpose, impact=impact, user_action=user_action))(None)


_hw("hardware.instance_connected", "Instrument connected", disruptive=False, severity="critical",
    desc="The instance reports connected.", requires=["bridge.online"],
    purpose="The instrument is reachable.",
    impact="This instrument's tests cannot run.",
    user_action=["Check instrument power", "Check the LAN/USB cable", "Re-test"])
_hw("hardware.identify", "Instrument identity", disruptive=False, severity="info",
    desc="*IDN?/identify() returns the expected vendor/model.",
    requires=["hardware.instance_connected"],
    purpose="The wired instrument matches the expected model.",
    impact="A wrong or incompatible instrument may be connected.",
    user_action=["Verify the correct instrument is wired to this channel", "Re-test"])
_hw("hardware.range_sane", "Reading in range", disruptive=False, severity="warning",
    desc="A read sits within the variable's expected range (catches floating/dead inputs).",
    requires=["hardware.instance_connected"],
    purpose="A live reading is within the expected range.",
    impact="Measurements may be wrong (floating or dead input).",
    user_action=["Check wiring and the sensor/DUT connection", "Re-test"])
_hw("hardware.self_test", "Instrument self-test", disruptive=True, severity="critical",
    desc="Driver self_test() passes. Disruptive — maintenance mode only.",
    requires=["hardware.instance_connected"],
    purpose="The instrument's built-in self-test passes.",
    impact="Measurements from this instrument cannot be trusted.",
    user_action=["Power-cycle the instrument", "Re-run in maintenance mode", "Calibrate or RMA if it persists"])
_hw("hardware.loopback", "Loopback", disruptive=True, severity="critical",
    desc="Drive a known output, read it back, assert within tolerance. Disruptive.",
    requires=["hardware.instance_connected"],
    purpose="Output drives and reads back within tolerance.",
    impact="Wiring or calibration drift; measurements are unreliable.",
    user_action=["Check the loopback wiring", "Recalibrate", "Re-test"])

"""Conformance suite — the existence gate (INSTRUMENT_LIBRARY.md §8).

One parametrized battery runs against EVERY registered library as an external
subject. A library that does not pass is not in `index.json` — it does not exist to
the builder, the tester, or a deployment. Human review is thereby reduced to the one
thing machinery can't check: command strings vs. the vendor manual.

`run_all(cls, make)` returns [(check_name, ok, detail)]; `make(**kw)` builds a fresh
SIM instance of `cls` (forwarding `fault_plan`/`timeout_s`). The library's sim +
identity must work headless — that is part of the interface contract (§3).
"""

from __future__ import annotations

import asyncio
import inspect

from instrumentlib.errors import CommandTimeout, InstrumentError, NotConnected
from instrumentlib.interfaces import CAPABILITIES
from instrumentlib.transport import FaultTransport, SimTransport


def _interfaces(cls):
    """Every capability interface a library declares (composite = more than one)."""
    return [CAPABILITIES[c] for c in cls._declaration["capabilities"]]


def _pick(methods, prefixes):
    return next((m for m in methods if any(m.startswith(p) or p in m for p in prefixes)), None)


def _sim_writes(inst):
    tp = inst.transport
    inner = tp.inner if isinstance(tp, FaultTransport) else tp
    return inner.writes if isinstance(inner, SimTransport) else []


# ---- individual checks (each returns (ok, detail)) ------------------------

def _check_declaration(cls):
    d = getattr(cls, "_declaration", None)
    if not d:
        return False, "no @instrument_library declaration"
    need = ("library_id", "vendor", "model", "capabilities", "interface_version",
            "transports", "library_version")
    miss = [k for k in need if not d.get(k)]
    return (not miss), f"missing {miss}" if miss else "ok"


def _check_interface_compliance(cls):
    """Every declared capability's method surface must be overridden (composite = all)."""
    unimpl = []
    for iface in _interfaces(cls):
        unimpl += [f"{iface.INTERFACE}.{m}" for m in iface.METHODS
                   if getattr(cls, m, None) is getattr(iface, m, None)]
    caps = ", ".join(i.INTERFACE for i in _interfaces(cls))
    return (not unimpl), f"not overridden: {unimpl}" if unimpl else f"{caps} complete"


def _check_no_class_mutable_state(cls):
    bad = []
    for klass in cls.__mro__:
        if klass.__name__ in ("InstrumentBase", "Capability", "object"):
            continue
        for name, val in vars(klass).items():
            if name.startswith("__"):
                continue
            if isinstance(val, (list, set)):            # dict/tuple allowed (command tables)
                bad.append(f"{klass.__name__}.{name}")
    return (not bad), f"mutable class state: {bad}" if bad else "clean"


async def _check_lock(make):
    inst = make()
    await inst.connect()
    order: list[str] = []

    async def probe():
        order.append("enter")
        await asyncio.sleep(0.01)
        order.append("exit")

    setattr(inst, "_probe", probe)
    await asyncio.gather(inst.invoke("_probe"), inst.invoke("_probe"))
    ok = order == ["enter", "exit", "enter", "exit"]
    return ok, "serialized" if ok else f"interleaved: {order}"


async def _check_sim_mode(make):
    inst = make()
    await inst.connect()
    for iface in _interfaces(_declared(make)):       # every declared capability
        read = _pick(iface.METHODS, ("measure", "read", "get"))
        if read:
            val = await inst.invoke(read, *_fabricate_args(iface, read))
            if not isinstance(val, (int, float, bool)):
                return False, f"{iface.INTERFACE}.{read} sim returned {val!r}"
        write = _pick(iface.METHODS, ("set", "write", "enable"))
        if write:
            before = len(_sim_writes(inst))
            try:
                await inst.invoke(write, *_fabricate_args(iface, write))
            except InstrumentError as e:
                return False, f"{write} raised in sim: {e}"
            if len(_sim_writes(inst)) <= before:
                return False, f"{write} not recorded"
    return True, "sim reads+writes ok"


async def _check_fault_battery(make):
    read, args = None, ()
    for iface in _interfaces(_declared(make)):       # one read exercises the transport plumbing
        read = _pick(iface.METHODS, ("measure", "read", "get"))
        if read:
            args = _fabricate_args(iface, read)
            break
    if read is None:
        return True, "no read method to fault"

    # timeout
    inst = make(fault_plan=[{"on": "any", "match": "*", "action": "timeout"}])
    await inst.connect()
    if not await _raises(inst, read, CommandTimeout, *args):
        return False, "timeout not raised as CommandTimeout"

    # error_response
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "error_response", "payload": "-113"}])
    await inst.connect()
    if not await _raises(inst, read, InstrumentError, *args):
        return False, "error_response not raised"

    # garbage -> must be an error, never a value
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "garbage"}])
    await inst.connect()
    if not await _raises(inst, read, InstrumentError, *args):
        return False, "garbage surfaced as a value (or wrong error)"

    # delay_ms beyond the budget -> timeout
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "delay_ms", "value": 2000}], timeout_s=0.05)
    await inst.connect()
    if not await _raises(inst, read, CommandTimeout, *args):
        return False, "delay_ms did not hit the timeout budget"

    # disconnect -> fail-fast NotConnected, then background reconnect to connected
    inst = make(fault_plan=[{"on": "any", "match": "*", "action": "disconnect", "once": True}],
                backoff_start_s=0.001)
    await inst.connect()
    if not await _raises(inst, read, NotConnected, *args):
        return False, "disconnect did not fail fast"
    for _ in range(200):
        if inst.state == inst.CONNECTED:
            break
        await asyncio.sleep(0.005)
    if inst.state != inst.CONNECTED:
        return False, f"did not reconnect (state={inst.state})"
    return True, "5 primitives ok"


async def _check_safe_emergency(make):
    inst = make()
    await inst.connect()
    try:
        await inst.safe_state()
        await inst.emergency_disable()
    except Exception as exc:  # noqa: BLE001
        return False, f"raised: {exc}"
    return True, "present + effective in sim"


# ---- helpers --------------------------------------------------------------

def _declared(make):
    return type(make())


def _fabricate_args(iface, method: str) -> tuple:
    """Plausible args for a capability method, from the INTERFACE signature — so a
    channel-parameterised read (read_voltage(channel)) is exercised with a channel and a
    nullary read (measure_voltage()) with none. Capability-agnostic (no hardcoded names)."""
    fn = getattr(iface, method)
    out: list = []
    for name, p in list(inspect.signature(fn).parameters.items())[1:]:   # skip self
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = p.annotation
        if ann is bool:
            out.append(True)
        elif ann is int:
            out.append(1)
        elif ann is str:
            out.append("cc" if name == "mode" else "0")
        else:                       # float / unannotated
            out.append(1.0)
    return tuple(out)


async def _raises(inst, method, exc_type, *args) -> bool:
    try:
        await inst.invoke(method, *args)
        return False
    except exc_type:
        return True
    except Exception:  # noqa: BLE001 — wrong error type
        return False


async def run_all(cls, make) -> list[tuple[str, bool, str]]:
    results = [
        ("declaration", *_check_declaration(cls)),
        ("interface_compliance", *_check_interface_compliance(cls)),
        ("no_class_mutable_state", *_check_no_class_mutable_state(cls)),
        ("lock_honored", *await _check_lock(make)),
        ("sim_mode", *await _check_sim_mode(make)),
        ("fault_battery", *await _check_fault_battery(make)),
        ("safe_state_emergency", *await _check_safe_emergency(make)),
    ]
    return results

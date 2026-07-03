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

from instrumentlib.errors import CommandTimeout, InstrumentError, NotConnected
from instrumentlib.interfaces import CAPABILITIES
from instrumentlib.transport import FaultTransport, SimTransport


def _interface(cls):
    return CAPABILITIES[cls._declaration["capability"]]


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
    need = ("library_id", "vendor", "model", "capability", "interface_version",
            "transports", "library_version")
    miss = [k for k in need if not d.get(k)]
    return (not miss), f"missing {miss}" if miss else "ok"


def _check_interface_compliance(cls):
    iface = _interface(cls)
    unimpl = [m for m in iface.METHODS if getattr(cls, m, None) is getattr(iface, m, None)]
    return (not unimpl), f"not overridden: {unimpl}" if unimpl else f"{iface.INTERFACE} complete"


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
    iface = _interface(_declared(make))
    inst = make()
    await inst.connect()
    read = _pick(iface.METHODS, ("measure", "read", "get"))
    val = await inst.invoke(read) if read else 0.0
    if read and not isinstance(val, (int, float, bool)):
        return False, f"{read} sim returned {val!r}"
    write = _pick(iface.METHODS, ("set", "write", "enable"))
    before = len(_sim_writes(inst))
    if write:
        try:
            await inst.invoke(write, *(_args_for(write)))
        except InstrumentError as e:
            return False, f"{write} raised in sim: {e}"
    wrote = len(_sim_writes(inst)) > before
    return (wrote or not write), "sim reads+writes ok" if (wrote or not write) else f"{write} not recorded"


async def _check_fault_battery(make):
    iface = _interface(_declared(make))
    read = _pick(iface.METHODS, ("measure", "read", "get"))
    if read is None:
        return True, "no read method to fault"

    # timeout
    inst = make(fault_plan=[{"on": "any", "match": "*", "action": "timeout"}])
    await inst.connect()
    if not await _raises(inst, read, CommandTimeout):
        return False, "timeout not raised as CommandTimeout"

    # error_response
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "error_response", "payload": "-113"}])
    await inst.connect()
    if not await _raises(inst, read, InstrumentError):
        return False, "error_response not raised"

    # garbage -> must be an error, never a value
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "garbage"}])
    await inst.connect()
    if not await _raises(inst, read, InstrumentError):
        return False, "garbage surfaced as a value (or wrong error)"

    # delay_ms beyond the budget -> timeout
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "delay_ms", "value": 2000}], timeout_s=0.05)
    await inst.connect()
    if not await _raises(inst, read, CommandTimeout):
        return False, "delay_ms did not hit the timeout budget"

    # disconnect -> fail-fast NotConnected, then background reconnect to connected
    inst = make(fault_plan=[{"on": "any", "match": "*", "action": "disconnect", "once": True}],
                backoff_start_s=0.001)
    await inst.connect()
    if not await _raises(inst, read, NotConnected):
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


def _args_for(method: str):
    if method.startswith("set_mode"):
        return ("cc",)
    if "enable" in method or method.startswith("write"):
        return (True,) if "digital" not in method else (0, True)
    return (1.0,)


async def _raises(inst, method, exc_type) -> bool:
    try:
        await inst.invoke(method)
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

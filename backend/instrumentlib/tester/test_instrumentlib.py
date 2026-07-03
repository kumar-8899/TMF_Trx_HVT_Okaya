"""instrumentlib framework-core tester (INSTRUMENT_LIBRARY.md §6, §8).

The reference library below is a CONFORMANCE TEST SUBJECT defined here (not a shipped
product library — those live in the separate library repo). It exercises the base,
the fault transport, the registry/index, and runs the full conformance battery.
"""

import asyncio

import pytest

from instrumentlib import (
    InstrumentBase,
    IPowerSource,
    SimTransport,
    build_index,
    emergency_disable_all,
    instrument_library,
)
from instrumentlib.base import _reset_instances
from instrumentlib.conformance import run_all
from instrumentlib.errors import (
    CommandTimeout,
    DeviceError,
    GarbageResponse,
    NotConnected,
)
from instrumentlib.registry import instrument_library as _decorate

IDN = "ACME,PS1,SN1,1.0"


@instrument_library(
    library_id="ref_supply", vendor="ACME", model="PS1",
    capability="power_source", interface_version=1, transports=["sim"],
    connection_params={}, library_version="1.0.0",
    generated_by="test", manual_reference="none",
)
class RefSupply(InstrumentBase, IPowerSource):
    # command table near the top of the class (§4.3) — a constant dict, review target
    CMD = {"idn": "*IDN?", "set_v": "VOLT {v}", "get_v": "VOLT?",
           "meas_v": "MEAS:VOLT?", "meas_i": "MEAS:CURR?", "ilim": "CURR {a}", "out": "OUTP {s}"}
    EXPECTED_IDN = "ACME"

    async def identify(self):
        return await self.transport.query(self.CMD["idn"])

    async def set_voltage(self, volts):
        await self.transport.write(self.CMD["set_v"].format(v=volts))

    async def get_voltage_setpoint(self):
        return float(await self.transport.query(self.CMD["get_v"]))

    async def measure_voltage(self):
        r = await self.transport.query(self.CMD["meas_v"])
        try:
            return float(r)
        except ValueError as e:
            raise GarbageResponse("implausible V", instance_id=self.instance_id, method="measure_voltage") from e

    async def measure_current(self):
        r = await self.transport.query(self.CMD["meas_i"])
        try:
            return float(r)
        except ValueError as e:
            raise GarbageResponse("implausible I", instance_id=self.instance_id, method="measure_current") from e

    async def set_current_limit(self, amps):
        await self.transport.write(self.CMD["ilim"].format(a=amps))

    async def output_enable(self, on):
        await self.transport.write(self.CMD["out"].format(s=1 if on else 0))

    async def safe_state(self):
        await self.transport.write(self.CMD["out"].format(s=0))

    async def emergency_disable(self):
        await self.transport.write(self.CMD["out"].format(s=0))


_RESP = {"*IDN?": IDN, "VOLT?": "12.0", "MEAS:VOLT?": "12.0", "MEAS:CURR?": "0.5"}


def make(idn=IDN, **kw):
    resp = dict(_RESP)
    resp["*IDN?"] = idn
    return RefSupply(
        "ref_1", transport=SimTransport(resp), simulated=True,
        fault_plan=kw.pop("fault_plan", None), timeout_s=kw.pop("timeout_s", 5.0),
        backoff_start_s=kw.pop("backoff_start_s", 0.001), **kw,
    )


@pytest.fixture(autouse=True)
def _clean_instances():
    _reset_instances()
    yield
    _reset_instances()


# ---- base behaviour -------------------------------------------------------

async def test_fail_fast_before_connect():
    inst = make()
    with pytest.raises(NotConnected):
        await inst.invoke("measure_voltage")


async def test_invoke_read_and_write_records():
    inst = make()
    await inst.connect()
    assert await inst.invoke("measure_voltage") == 12.0
    await inst.invoke("set_voltage", 5.0)
    assert "VOLT 5.0" in inst.transport.writes


async def test_diagnostics_emitted_per_command():
    recs = []
    inst = make(on_command=recs.append)
    await inst.connect()
    await inst.invoke("measure_current")
    cmd = [r for r in recs if r["kind"] == "command"][-1]
    assert cmd["method"] == "measure_current" and cmd["outcome"] == "ok" and cmd["elapsed_ms"] >= 0


async def test_lock_serializes_concurrent_calls():
    inst = make()
    await inst.connect()
    order = []

    async def probe():
        order.append("in"); await asyncio.sleep(0.01); order.append("out")

    setattr(inst, "_probe", probe)
    await asyncio.gather(inst.invoke("_probe"), inst.invoke("_probe"))
    assert order == ["in", "out", "in", "out"]


# ---- fault battery (the five primitives) ----------------------------------

async def test_fault_timeout():
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "timeout"}])
    await inst.connect()
    with pytest.raises(CommandTimeout):
        await inst.invoke("measure_voltage")


async def test_fault_after_n_write():
    inst = make(fault_plan=[{"on": "write", "match": "VOLT*", "action": "timeout", "after_n": 3}])
    await inst.connect()
    await inst.invoke("set_voltage", 1)      # 1
    await inst.invoke("set_voltage", 2)      # 2
    with pytest.raises(CommandTimeout):
        await inst.invoke("set_voltage", 3)  # 3rd -> fires


async def test_fault_error_response_maps_to_device_error():
    inst = make(fault_plan=[{"on": "read", "match": "MEAS*", "action": "error_response", "payload": "-113"}])
    await inst.connect()
    with pytest.raises(DeviceError):
        await inst.invoke("measure_voltage")


async def test_fault_garbage_never_a_value():
    inst = make(fault_plan=[{"on": "read", "match": "MEAS*", "action": "garbage"}])
    await inst.connect()
    with pytest.raises(GarbageResponse):
        await inst.invoke("measure_voltage")


async def test_fault_delay_hits_timeout_budget():
    inst = make(fault_plan=[{"on": "read", "match": "*", "action": "delay_ms", "value": 2000}], timeout_s=0.05)
    await inst.connect()
    with pytest.raises(CommandTimeout):
        await inst.invoke("measure_voltage")


async def test_fault_disconnect_reconnects_and_reverifies_identity():
    inst = make(fault_plan=[{"on": "any", "match": "*", "action": "disconnect", "once": True}])
    await inst.connect()
    with pytest.raises(NotConnected):
        await inst.invoke("measure_voltage")     # fail-fast
    for _ in range(200):
        if inst.state == inst.CONNECTED:
            break
        await asyncio.sleep(0.005)
    assert inst.state == inst.CONNECTED           # reconnected + identity re-verified


async def test_reconnect_identity_mismatch_faults():
    inst = make(idn="WRONG,DEVICE", fault_plan=[{"on": "any", "match": "*", "action": "disconnect", "once": True}])
    await inst.connect()
    with pytest.raises(NotConnected):
        await inst.invoke("measure_voltage")
    for _ in range(200):
        if inst.state in (inst.FAULTED, inst.CONNECTED):
            break
        await asyncio.sleep(0.005)
    assert inst.state == inst.FAULTED             # mismatch -> hard fault, no resume


# ---- emergency fan-out + registry/index -----------------------------------

async def test_emergency_disable_fans_out():
    a, b = make(), make()
    await a.connect(); await b.connect()
    await emergency_disable_all()
    assert "OUTP 0" in a.transport.writes and "OUTP 0" in b.transport.writes


def test_duplicate_library_id_fails_loud():
    with pytest.raises(ValueError):
        @_decorate(library_id="ref_supply", vendor="X", model="Y", capability="power_source",
                   interface_version=1, transports=["sim"], library_version="1.0.0")
        class _Dup(InstrumentBase, IPowerSource):
            pass


def test_index_lists_the_library():
    idx = build_index()
    ref = next(l for l in idx["libraries"] if l["library_id"] == "ref_supply")
    assert ref["capability"] == "power_source" and ref["scalar"] is True and "class" not in ref


# ---- the conformance gate itself ------------------------------------------

async def test_reference_library_passes_conformance():
    results = await run_all(RefSupply, make)
    failed = [(n, d) for (n, ok, d) in results if not ok]
    assert failed == [], f"conformance failures: {failed}"

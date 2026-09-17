#!/usr/bin/env python
"""Live hardware probe for one hipot AC-withstand reading, using the real `hipot` and relay
instances configured on Config -> Instruments (reads their params straight from the live DB,
same pattern as probe_relay.py).

Mirrors exactly what the `hipot_acw` step type does (app/okaya_hvt/okaya_hvt_steps/hipot_acw/
handler.py): energise ONE routing relay channel, settle, run measure_acw on the real UT5320R+,
report the raw reading, then ALWAYS de-energise that same channel in a finally block -- whether
the test passed, failed, or errored. This is a raw hardware check, not a judged test: it prints
the leakage current + breakdown flag with no pass/fail limit applied (that's the recipe layer's
job, not this tool's).

Only ever touches ONE relay channel at a time, and never calls the relay's safe_state() (which
sweeps every channel up to the configured num_channels and is currently known to throw a Modbus
exception on this hardware once it hits an out-of-range channel -- see probe_relay.py) -- it
explicitly turns off only the channel it turned on, before ever touching the next one. Multiple
`--channel` values run strictly sequentially: each channel is fully de-energised (in a per-
channel finally block, even on error) before the next channel is energised -- never two routes
closed at once.

    python app/okaya_hvt/tools/probe_hipot_acw.py --relay relay1 --channel 0 --kv 0.5 --time 10
    python app/okaya_hvt/tools/probe_hipot_acw.py --relay relay1 --channel 0 1 2 3 4 5 --kv 0.5 --time 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]         # app/okaya_hvt
FORK_ROOT = APP_DIR.parents[1]                         # repo root (holds instrument_libs/)
DB_PATH = FORK_ROOT / "backend" / "data" / "tmf.sqlite"

for _p in (str(FORK_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import instrument_libs  # noqa: E402,F401 -- registers the bench drivers
from instrumentlib import REGISTRY  # noqa: E402


def load_instrument_record(instance_id: str) -> dict:
    if not DB_PATH.exists():
        raise SystemExit(f"no runtime DB at {DB_PATH} -- has the backend ever run here?")
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute(
            "select data from records where type='instrument' and id=?", (instance_id,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise SystemExit(f"no instrument record '{instance_id}' in {DB_PATH} "
                          f"-- configure it on Config -> Instruments first")
    return json.loads(row[0])


# channel -> the maps/st1.json signal name, for readable output only.
ROUTE_NAMES = {
    0: "hipot_route_pri_sec", 1: "hipot_route_pri_core", 2: "hipot_route_sec_core",
    3: "hipot_route_fb_core", 4: "hipot_route_pri_fb", 5: "hipot_route_sec_fb",
}


def build(instance_id: str):
    rec = load_instrument_record(instance_id)
    entry = REGISTRY.get(rec["library"])
    if entry is None:
        raise SystemExit(f"library '{rec['library']}' not registered for instance '{instance_id}'")
    simulated = bool(rec.get("simulated", False))
    inst = entry["class"](instance_id, simulated=simulated, params=rec.get("params", {}))
    return inst, rec, simulated


async def run_one(relay, hipot, relay_id: str, channel: int, voltage_v: float, dwell_s: float,
                  step: int, settle_s: float) -> dict:
    name = ROUTE_NAMES.get(channel, f"ch{channel}")
    print(f"\n=== {relay_id} ch{channel} ({name}) ===")
    energised = False
    result = {"channel": channel, "name": name, "ok": False, "leakage_ma": None,
              "breakdown": None, "error": None}
    try:
        print(f"[1/3] energising {relay_id} ch{channel} ...")
        await relay.write_digital(channel, True)
        energised = True
        time.sleep(settle_s)

        print(f"[2/3] running measure_acw({voltage_v:.0f}, {dwell_s:.1f}, step={step}) ...")
        leakage_ma, breakdown = await hipot.measure_acw(voltage_v, dwell_s, step)
        result.update(ok=True, leakage_ma=leakage_ma, breakdown=breakdown)
        print(f"      RESULT: leakage = {leakage_ma:.4g} mA   breakdown = {breakdown}")
    except Exception as exc:  # noqa: BLE001 -- report, don't hide
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(f"      TEST FAILED: {result['error']}")
    finally:
        print(f"[3/3] de-energising {relay_id} ch{channel} ...")
        if energised:
            try:
                await relay.write_digital(channel, False)
                print("      route open confirmed commanded OFF")
            except Exception as exc:  # noqa: BLE001
                result["error"] = (result["error"] or "") + f" | FAILED TO OPEN ROUTE: {exc}"
                print(f"      FAILED TO OPEN ROUTE: {type(exc).__name__}: {exc} "
                      f"-- de-energise ch{channel} on {relay_id} manually now")
        try:
            await hipot.safe_state()
        except Exception as exc:  # noqa: BLE001
            print(f"      hipot safe_state() FAILED: {type(exc).__name__}: {exc}")
    return result


async def run(relay_id: str, channels: list[int], voltage_v: float, dwell_s: float, step: int,
              settle_s: float) -> int:
    relay, relay_rec, relay_sim = build(relay_id)
    hipot, hipot_rec, hipot_sim = build("hipot")

    print(f"relay:  {relay_id}  params={json.dumps(relay_rec.get('params', {}))}  simulated={relay_sim}")
    print(f"hipot:  params={json.dumps(hipot_rec.get('params', {}))}  simulated={hipot_sim}")
    print(f"test:   {voltage_v:.0f} V AC, {dwell_s:.1f} s dwell, step {step}, "
          f"channels {channels} on {relay_id} -- one at a time")

    await relay.connect()
    await hipot.connect()

    try:
        results = []
        for channel in channels:
            results.append(await run_one(relay, hipot, relay_id, channel, voltage_v, dwell_s, step, settle_s))

        print("\n=== summary ===")
        any_bad = False
        for r in results:
            if r["ok"]:
                print(f"  ch{r['channel']} {r['name']:22} leakage={r['leakage_ma']:.4g} mA  "
                      f"breakdown={r['breakdown']}")
                any_bad = any_bad or bool(r["breakdown"])
            else:
                print(f"  ch{r['channel']} {r['name']:22} ERROR: {r['error']}")
                any_bad = True
        return 1 if any_bad else 0
    finally:
        # Always release both connections -- the supervised Python controller (controller.kind
        # == "python") holds its own live connection to these same physical instruments, and
        # most of these serial-to-Ethernet/Modbus-TCP/VISA-TCP bridges only accept ONE client at
        # a time (INSTRUMENT_LIBRARY.md §9.3 shared-instrument rule). A probe that exits without
        # disconnecting can leave a stale session on the bridge that confuses the controller's
        # own subsequent reads/writes -- never run this probe while a recipe might be running,
        # and never skip this disconnect.
        for name, inst in (("relay", relay), ("hipot", hipot)):
            try:
                await inst.disconnect()
            except Exception as exc:  # noqa: BLE001
                print(f"{name} disconnect() FAILED (device may still consider this client "
                      f"connected): {type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--relay", default="relay1", help="relay instance carrying the route (default: relay1)")
    ap.add_argument("--channel", type=int, nargs="+", required=True,
                     help="route channel(s) to energise, e.g. 0 for hipot_route_pri_sec, or 0 1 2 3 4 5 for all six")
    ap.add_argument("--kv", type=float, help="AC withstand voltage in kV (e.g. 0.5)")
    ap.add_argument("--volts", type=float, help="AC withstand voltage in V (alternative to --kv)")
    ap.add_argument("--time", type=float, required=True, dest="dwell_s", help="test (dwell) time in seconds")
    ap.add_argument("--step", type=int, default=1, help="tester program step (default: 1)")
    ap.add_argument("--settle-s", type=float, default=0.2, help="settle time after closing the route (default: 0.2s)")
    args = ap.parse_args()

    if args.kv is None and args.volts is None:
        ap.error("pass --kv or --volts")
    voltage_v = args.volts if args.volts is not None else args.kv * 1000.0

    return asyncio.run(run(args.relay, args.channel, voltage_v, args.dwell_s, args.step, args.settle_s))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Live hardware probe for a `waveshare_modbus_relay` instance configured on Config -> Instruments.

Reads the instance's real params straight out of the running app's own instrument records (no
IP/port to retype, no risk of testing against stale values), connects for real (NOT simulated),
calls identify() to prove the Modbus link, then does a brief, visible ON/OFF toggle of each
requested channel (default: 0.6s ON / 0.6s OFF, one channel at a time) so a person standing at
the bench can confirm the right lamp/relay/buzzer actually moves.

Only ever touches the channels you pass in -- it does not sweep every channel on the card, so
it's safe to point at a routing relay too as long as you only ask for channels you know aren't
mid-test. For relay2 (tower-light stack) the default channels are 0,1,2 (tl_red/tl_green/buzzer)
since those are cosmetic/audible and low-risk to toggle; there is no such default for relay1
(hipot routes) -- pass -c explicitly if you really mean to energise a hipot route with no DUT/HV
applied, and know what you're doing.

    python app/okaya_hvt/tools/probe_relay.py relay2
    python app/okaya_hvt/tools/probe_relay.py relay2 -c 0 1 2
    python app/okaya_hvt/tools/probe_relay.py relay1 -c 0          # explicit, no default

Must run on a machine that actually has a network path to the instrument's configured host --
this only proves the Modbus link, it doesn't work around a missing route."""

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


async def probe(instance_id: str, channels: list[int], hold_s: float) -> int:
    rec = load_instrument_record(instance_id)
    lib_id = rec["library"]
    params = rec.get("params", {})
    simulated = bool(rec.get("simulated", False))

    print(f"instance:  {instance_id}")
    print(f"library:   {lib_id}")
    print(f"params:    {json.dumps(params)}")
    print(f"simulated: {simulated}")
    if simulated:
        print("\nThis instance is configured SIMULATED -- nothing real will be touched. "
              "Flip Simulated off on Config -> Instruments first if you want a real probe.")

    entry = REGISTRY.get(lib_id)
    if entry is None:
        raise SystemExit(f"library '{lib_id}' not registered -- is instrument_libs imported?")

    inst = entry["class"](instance_id, simulated=simulated, params=params)
    print(f"\nconnecting to {params.get('host')}:{params.get('port', params.get('resource', '?'))} ...")
    try:
        await inst.connect()
    except Exception as exc:  # noqa: BLE001 -- report, don't crash ugly
        print(f"CONNECT FAILED: {type(exc).__name__}: {exc}")
        return 1

    try:
        try:
            idn = await inst.identify()
            print(f"identify(): {idn}")
        except Exception as exc:  # noqa: BLE001
            print(f"identify() FAILED: {type(exc).__name__}: {exc}")
            return 1

        if not channels:
            print("\nno channels given -- link + identify confirmed, skipping toggle test.")
            return 0

        print(f"\ntoggling channels {channels} ({hold_s}s ON / {hold_s}s OFF each) -- watch the bench:")
        ok = True
        for ch in channels:
            try:
                print(f"  ch{ch} ON")
                await inst.write_digital(ch, True)
                time.sleep(hold_s)
                print(f"  ch{ch} OFF")
                await inst.write_digital(ch, False)
                time.sleep(hold_s)
            except Exception as exc:  # noqa: BLE001
                print(f"  ch{ch} FAILED: {type(exc).__name__}: {exc}")
                ok = False

        try:
            await inst.safe_state()
        except Exception as exc:  # noqa: BLE001
            print(f"safe_state() FAILED (channels may still be energised!): {type(exc).__name__}: {exc}")
            ok = False

        print("\nRESULT:", "PASS -- link confirmed, every channel toggled and returned to safe state"
              if ok else "FAIL -- see errors above; do not treat this instance as verified")
        return 0 if ok else 1
    finally:
        # Always release the connection -- this instance's real owner (the supervised Python
        # controller, when controller.kind == "python") holds its own live connection to the
        # same physical device, and most of these serial-to-Ethernet/Modbus-TCP bridges only
        # accept ONE client at a time (INSTRUMENT_LIBRARY.md §9.3 shared-instrument rule). A
        # probe run that exits without disconnecting can leave a stale session on the bridge
        # that confuses the controller's own subsequent reads/writes -- never run this probe
        # while a recipe might be running, and never skip this disconnect.
        try:
            await inst.disconnect()
        except Exception as exc:  # noqa: BLE001
            print(f"disconnect() FAILED (device may still consider this client connected): "
                  f"{type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("instance_id", help="instrument instance id, e.g. relay2")
    ap.add_argument("-c", "--channels", type=int, nargs="*", default=None,
                     help="channels to toggle (default: 0 1 2 for relay2 only; required for anything else)")
    ap.add_argument("--hold-s", type=float, default=0.6, help="seconds to hold each ON/OFF state")
    args = ap.parse_args()

    channels = args.channels
    if channels is None:
        channels = [0, 1, 2] if args.instance_id == "relay2" else []

    return asyncio.run(probe(args.instance_id, channels, args.hold_s))


if __name__ == "__main__":
    raise SystemExit(main())

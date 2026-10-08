"""Release-gate helper: drive the BUILT exe's controller (`run.exe --controller`) over MQTT.

Why: native-driver bugs (NI-DAQmx access violation from a bundled Qt MSVCP140.dll, missing package
metadata, ...) only exist in the frozen exe, and only when a real driver call is made - `connect()`
and the HTTP API never reach them. Each probe in app/<slug>/release-probes.json -> "controller_probes":

  { "name": "ni_task", "instance": {"id": "ni", "library": "ni_usb6001", "params": {"device": "Dev1"}},
    "requires_nidaqmx_device": "Dev1",
    "calls": [{"method": "read_voltage", "args": ["ai0"]}, ...] }

Only READ-type calls belong here: the build PC's device may be real hardware.
A probe whose required device is absent is SKIPPED (reported, never silently passed).
Exit code 0 = all run probes passed, 1 = a probe failed, 2 = setup error.
Usage: python verify_controller_probe.py <run.dist dir> <release-probes.json> [--port 18831]
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOSQ = HERE / "vendor" / "mosquitto" / "win64" / "mosquitto.exe"
STATION = "st9"


def _kill(p: subprocess.Popen | None) -> None:
    if p and p.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)


def _nidaqmx_devices() -> list[str] | None:
    try:
        import nidaqmx.system
        return [d.name for d in nidaqmx.system.System.local().devices]
    except Exception:  # noqa: BLE001 - no driver on this PC
        return None


def run_probe(dist: Path, probe: dict, port: int, tmp: Path) -> tuple[str, list[str]]:
    import paho.mqtt.client as mqtt

    need = probe.get("requires_nidaqmx_device")
    if need:
        devs = _nidaqmx_devices()
        if devs is None or need not in devs:
            return "SKIP", [f"required NI device {need!r} not present on this PC (present: {devs})"]

    conf = tmp / "mosq.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n", encoding="ascii")
    inst = dict(probe["instance"], simulated=False, stations=[STATION])
    cfg = {"schema_version": 1, "broker": {"host": "127.0.0.1", "port": port},
           "library_packages": probe.get("library_packages", ["instrument_libs"]),
           "step_type_packages": [], "stations": [{"station": STATION}], "simulation": False,
           "instruments": [inst]}
    cfg_file = tmp / "ctl.json"
    cfg_file.write_text(json.dumps(cfg), encoding="ascii")

    broker = ctl = None
    lines: list[str] = []
    errf = open(tmp / "ctl.err", "w+")
    try:
        broker = subprocess.Popen([str(MOSQ), "-c", str(conf)], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        ctl = subprocess.Popen([str(dist / "run.exe"), "--controller", str(cfg_file)], cwd=str(dist),
                               stdout=subprocess.DEVNULL, stderr=errf)
        got: dict[str, dict] = {}
        client = (mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                  if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client())
        client.on_message = lambda c, u, m: got.__setitem__(json.loads(m.payload).get("id"),
                                                             json.loads(m.payload))
        for _ in range(40):
            try:
                client.connect("127.0.0.1", port)
                break
            except OSError:
                time.sleep(0.25)
        client.loop_start()
        reply_to = f"tmf/{STATION}/query/resp/gate"
        client.subscribe(reply_to)
        time.sleep(8.0)  # controller boot + instrument connect

        failed = False
        for call in probe["calls"]:
            rid = uuid.uuid4().hex
            t0 = time.time()
            client.publish(f"tmf/{STATION}/cmd/instrument.call", json.dumps(
                {"id": rid, "op": "instrument.call", "reply_to": reply_to,
                 "args": {"instance_id": inst["id"], "method": call["method"],
                          "args": call.get("args", [])}}), qos=1)
            while rid not in got and time.time() - t0 < 30:
                time.sleep(0.05)
            r = got.get(rid)
            label = f"{inst['id']}.{call['method']}{call.get('args', [])}"
            if r is None:
                lines.append(f"{label}: NO REPLY in 30 s"); failed = True
            elif not r.get("ok"):
                lines.append(f"{label}: {r.get('error')}"); failed = True
            else:
                lines.append(f"{label}: ok ({time.time() - t0:.2f} s) -> {r.get('result')!r}"[:160])
        client.loop_stop()
        if failed:
            errf.flush(); errf.seek(0)
            tail = errf.read().strip().splitlines()[-12:]
            lines.append("controller stderr (tail): " + " | ".join(t.strip() for t in tail))
        return ("FAIL" if failed else "PASS"), lines
    finally:
        _kill(ctl)
        _kill(broker)
        errf.close()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__); return 2
    dist, probes_file = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 18831
    if not (dist / "run.exe").exists() or not MOSQ.exists():
        print(f"setup error: need {dist / 'run.exe'} and {MOSQ}"); return 2
    probes = json.loads(probes_file.read_text(encoding="utf-8")).get("controller_probes", [])
    rc = 0
    for probe in probes:
        with tempfile.TemporaryDirectory(prefix="tmf-ctlprobe-") as tmp:
            verdict, lines = run_probe(dist, probe, port, Path(tmp))
        print(f"{verdict}  controller probe '{probe['name']}'")
        for ln in lines:
            print(f"      {ln}")
        if verdict == "FAIL":
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

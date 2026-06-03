# deploy/ — broker, bundling, local run

The MQTT broker is **Mosquitto**, a standalone program (not Python, not
LabVIEW). Both sides are clients of it (LABVIEW_BRIDGE.md §2). One local broker
per station, bound to loopback.

## Files

| File | Purpose |
|---|---|
| `mosquitto.conf` | Station broker config — loopback `127.0.0.1:1883`, anonymous (local trust boundary). Central-uplink template commented in. |
| `fetch-mosquitto.ps1` | Vendors the broker runtime into `vendor/mosquitto/win64/` for bundling. |
| `run-local.ps1` | Brings up broker + app + LabVIEW stub for a graphical-first demo. |
| `vendor/` | Vendored broker runtime (gitignored; produced by the fetch script). |

## Shipping the broker with the installer

The station installer (Tauri) bundles Mosquitto so the operator never installs
it by hand.

1. **Build prep** — `./deploy/fetch-mosquitto.ps1` downloads the official build
   and copies the minimal runtime (`mosquitto.exe` + DLLs + `mosquitto.conf`)
   into `deploy/vendor/mosquitto/win64/`. CI/build runs this before packaging.
2. **Bundle** — Tauri ships that folder as a resource. When the Tauri shell is
   scaffolded, `src-tauri/tauri.conf.json` will carry:
   ```jsonc
   {
     "bundle": {
       "resources": { "../deploy/vendor/mosquitto/win64": "mosquitto" }
     }
   }
   ```
3. **Launch** — on station start, the shell spawns the bundled broker
   (`mosquitto -c mosquitto.conf`) before the Python sidecar connects, then the
   LabVIEW controller and the browser connect to the same loopback broker. The
   Python bridge already retries until the broker is up (`bridge.py`
   supervisor), so ordering is forgiving.

`deploy/run-local.ps1` already demonstrates the launch sequence and prefers the
vendored broker when present.

## Verify it works

```pwsh
./deploy/fetch-mosquitto.ps1     # once, to vendor the broker
./deploy/run-local.ps1           # broker + app + stub
```

Then watch `tmf/#` in MQTT Explorer and hit
`http://127.0.0.1:8000/hello/ping` (see ../docs/PHASE0_ACCEPTANCE.md).

## Note: stray Mosquitto service

The official Windows installer registers an **always-on `mosquitto` Windows
service** on port 1883. The bundled-broker model does not want that (the shell
manages the broker per station). If a machine has that service from a prior
install, disable it (admin shell), or it will hold 1883:

```pwsh
Stop-Service mosquitto; Set-Service mosquitto -StartupType Disabled
```

The test suite is unaffected — it spins brokers on ephemeral ports.
